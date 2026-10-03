#!/usr/bin/env python3
"""Drive the S1100FX MAME test machine headlessly (emu/bin/s1100fx).

    python3 tools/s1100test.py boot build/S1100FX.img          # show the LCD after boot
    python3 tools/s1100test.py boot build/S1100FX.img --press KEY3:MIDI
    python3 tools/s1100test.py run steps.txt build/S1100FX.img  # run a step file

Step files are documented in emu/lua/harness.lua. The OS (raw file or the
OS inside an Akai floppy image) is loaded with -quickload; a floppy image
is also inserted in the drive. MAME runs unthrottled with no video or
sound output, so a boot plus a few key presses takes a few seconds.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAME = os.environ.get("S1100FX_MAME", os.path.join(ROOT, "emu", "bin", "s1100fx"))
HARNESS = os.path.join(ROOT, "emu", "lua", "harness.lua")
FLOPPY_SIZES = (819200, 1638400)
FRAMES_PER_SECOND = 80  # the driver's LCD refresh rate
# MAME's HD61830 model insists on the controller's internal character ROM.
# The S1100 runs the LCD in graphics mode and never uses it, so a blank
# placeholder of the right size is generated for each run.
PLACEHOLDER_ROMS = {"hd61830.bin": 0x5C0}


class MameError(Exception):
    pass


# The S1100 OS draws text itself with a 5x7 font in 6-pixel cells. The font
# is read from the OS under test (see find_font), never stored here.
GLYPH_A = bytes.fromhex("040a11111f111100")


def find_font(os_data):
    """Locate the OS's 8-bytes-per-glyph font (ASCII from 0x20, leftmost
    pixel in bit 0) and return {char: 7-row tuple}."""
    a = os_data.find(GLYPH_A)
    base = a - (ord("A") - 0x20) * 8
    if a < 0 or base < 0 or any(os_data[base:base + 8]):
        raise MameError("could not find the OS font")
    font = {}
    for code in range(0x21, 0x7F):
        g = os_data[base + (code - 0x20) * 8: base + (code - 0x20) * 8 + 7]
        rows = tuple(sum(((b >> i) & 1) << (4 - i) for i in range(5)) for b in g)
        font.setdefault(rows, chr(code))
    return font


def os_from_image(path):
    """The OS bytes inside a raw OS file or an Akai floppy image."""
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import akaidisk
    with open(path, "rb") as f:
        data = f.read()
    if len(data) not in FLOPPY_SIZES:
        return data
    disk = akaidisk.AkaiFloppy(data)
    for e in disk.entries():
        if e.used and e.type == 0x63:
            return disk.read_file(e)
    raise MameError(f"no OS file on {path}")


class Lcd:
    """A 240x64 LCD capture: rows of booleans (True = pixel on)."""

    def __init__(self, text, font=None):
        self.rows = [[c == "#" for c in line] for line in text.splitlines() if line]
        self.font = font

    def _key(self, x, y, inv):
        rows = []
        for r in self.rows[y:y + 7]:
            v = 0
            for p in r[x:x + 5]:
                v = (v << 1) | (p ^ inv)
            rows.append(v)
        return tuple(rows)

    def _clear(self, x, y, w, h, inv):
        """True if the box is entirely background (in this polarity)."""
        H, W = len(self.rows), len(self.rows[0])
        for yy in range(y, y + h):
            for xx in range(x, x + w):
                if 0 <= yy < H and 0 <= xx < W and self.rows[yy][xx] ^ inv:
                    return False
        return True

    def text_items(self):
        """[(y, x, char, inverted)] for every glyph found on screen."""
        if not self.font:
            raise MameError("no font: pass font= or use run(), which reads it from the OS")
        H, W = len(self.rows), len(self.rows[0])
        items = []
        for inv in (False, True):
            for y in range(0, H - 6):
                for x in range(0, W - 4):
                    ch = self.font.get(self._key(x, y, inv))
                    if ch and self._clear(x - 1, y, 1, 7, inv) and self._clear(x + 5, y, 1, 7, inv) \
                            and self._clear(x, y - 1, 5, 1, inv) and self._clear(x, y + 7, 5, 1, inv):
                        items.append((y, x, ch, inv))
        return sorted(items)

    def lines(self):
        """Screen text as {y: string}, with gaps turned into spaces."""
        out = {}
        for y, x, ch, _ in self.text_items():
            line = out.setdefault(y, [])
            line.append((x, ch))
        text = {}
        for y, chars in out.items():
            s, last = "", None
            for x, ch in sorted(chars):
                if last is not None:
                    s += " " * max(0, round((x - last) / 6) - 1)
                s += ch
                last = x
            text[y] = s
        return dict(sorted(text.items()))

    def text(self):
        return "\n".join(self.lines().values())

    def contains(self, s):
        return any(s in line for line in self.lines().values())

    @property
    def size(self):
        return (len(self.rows[0]) if self.rows else 0, len(self.rows))

    def lit(self):
        return sum(map(sum, self.rows))

    def art(self, on="#", off=" "):
        return "\n".join("".join(on if p else off for p in row) for row in self.rows)

    def diff(self, other):
        """Pixel positions that differ, as (x, y)."""
        return [(x, y) for y, (a, b) in enumerate(zip(self.rows, other.rows))
                for x, (p, q) in enumerate(zip(a, b)) if p != q]

    def region(self, x, y, w, h):
        return [row[x:x + w] for row in self.rows[y:y + h]]

    def __eq__(self, other):
        return self.rows == other.rows


def available():
    return os.access(MAME, os.X_OK)


def run(steps, quickload, floppy=None, timeout=300, keep=None):
    """Run MAME with a step list (strings); return ({snap name: Lcd},
    {mem name: bytes}, harness log text)."""
    if not available():
        raise MameError(f"MAME test machine not built: {MAME} (run emu/mame/build.sh)")
    if floppy is None and os.path.getsize(quickload) in FLOPPY_SIZES:
        floppy = quickload
    if steps[-1].split()[0] != "exit":
        steps = list(steps) + ["exit"]
    tmp = os.path.abspath(keep) if keep else tempfile.mkdtemp(prefix="s1100fx-")
    try:
        roms = os.path.join(tmp, "roms", "s1100fx")
        os.makedirs(roms, exist_ok=True)
        for name, size in PLACEHOLDER_ROMS.items():
            with open(os.path.join(roms, name), "wb") as f:
                f.write(bytes(size))
        steps_path = os.path.join(tmp, "steps.txt")
        with open(steps_path, "w") as f:
            f.write("\n".join(steps) + "\n")
        cmd = [MAME, "s1100fx", "-quickload", os.path.abspath(quickload),
               "-video", "none", "-sound", "none", "-nothrottle", "-skip_gameinfo",
               "-nomouse", "-window", "-autoboot_script", HARNESS,
               "-rompath", os.path.join(tmp, "roms"),
               "-homepath", tmp, "-cfg_directory", tmp, "-nvram_directory", tmp,
               "-snapshot_directory", tmp, "-diff_directory", tmp]
        if floppy:
            cmd += ["-flop", os.path.abspath(floppy)]
        env = dict(os.environ, S1100FX_STEPS=steps_path, S1100FX_OUT=tmp,
                   SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy")
        p = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout, cwd=tmp)
        log_path = os.path.join(tmp, "harness.log")
        log = ""
        if os.path.exists(log_path):
            with open(log_path) as f:
                log = f.read()
        if p.returncode != 0 or "exit" not in log:
            raise MameError(f"MAME exited with {p.returncode}\n{p.stdout[-2000:]}\n{p.stderr[-2000:]}\n{log}")
        font = find_font(os_from_image(quickload))
        snaps, mems = {}, {}
        for name in os.listdir(tmp):
            base, ext = os.path.splitext(name)
            if ext == ".lcd":
                with open(os.path.join(tmp, name)) as f:
                    snaps[base] = Lcd(f.read(), font)
            elif ext == ".bin":
                with open(os.path.join(tmp, name), "rb") as f:
                    mems[base] = f.read()
        return snaps, mems, log
    finally:
        if keep is None:
            shutil.rmtree(tmp, ignore_errors=True)


def boot_steps(seconds=8, presses=(), settle=1.0):
    steps = [f"wait {int(seconds * FRAMES_PER_SECOND)}", "snap boot"]
    for i, key in enumerate(presses):
        port, field = key.split(":", 1)
        steps += [f"press {port} {field}", f"wait {int(settle * FRAMES_PER_SECOND)}", f"snap press{i + 1}"]
    return steps


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("boot", help="boot, optionally press keys, print the LCD")
    s.add_argument("image")
    s.add_argument("--seconds", type=float, default=8)
    s.add_argument("--press", action="append", default=[], metavar="PORT:KEY",
                   help="e.g. KEY3:MIDI (see the driver's input ports)")
    s.add_argument("--keep", metavar="DIR", help="keep MAME's output files here")
    s = sub.add_parser("run", help="run a step file")
    s.add_argument("steps")
    s.add_argument("image")
    s.add_argument("--keep", metavar="DIR")
    args = ap.parse_args(argv)

    if args.keep:
        os.makedirs(args.keep, exist_ok=True)
    if args.cmd == "boot":
        steps = boot_steps(args.seconds, args.press)
    else:
        with open(args.steps) as f:
            steps = [line for line in f.read().splitlines() if line.strip()]
    try:
        snaps, _, _ = run(steps, args.image, keep=args.keep)
    except MameError as exc:
        print("error:", exc, file=sys.stderr)
        return 2
    for name in sorted(snaps):
        lcd = snaps[name]
        print(f"--- {name} ({lcd.lit()} pixels lit)")
        print(lcd.art())
        print("--- text")
        for y, line in lcd.lines().items():
            print(f"  y={y:2d}  {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
