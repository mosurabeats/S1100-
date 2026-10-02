#!/usr/bin/env python3
"""S1100FX vintage + auto-chop: bit-exact reference model and WAV tool.

This file defines exactly what the V50 assembly in src/dsp/ must compute.
The tests run the assembly in an x86-16 emulator and compare it against
these functions sample for sample, so any change here must be mirrored in
the assembly (and vice versa). Integer arithmetic only.

  presets                      list presets
  crush IN.wav OUT.wav -p ID   apply a vintage preset (hear it on a computer)
  chop IN.wav -n 16 [-o DIR]   find slice points; optionally write slices
  gen-inc                      emit src/dsp/presets.inc from presets/vintage.toml
"""

import argparse
import os
import sys
import tomllib
import wave
from array import array

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRESETS_TOML = os.path.join(ROOT, "presets", "vintage.toml")
NAME_LEN = 10

# Limits shared with the assembly.
MAX_GAIN = 400  # percent
MIN_BITS, MAX_BITS = 1, 16


def load_presets(path=PRESETS_TOML):
    with open(path, "rb") as f:
        presets = tomllib.load(f)["preset"]
    for p in presets:
        if not MIN_BITS <= p["bits"] <= MAX_BITS:
            raise ValueError(f"{p['id']}: bits out of range")
        if not 0 <= p["rate"] <= 65535:
            raise ValueError(f"{p['id']}: rate out of range")
        if not 1 <= p["gain"] <= MAX_GAIN:
            raise ValueError(f"{p['id']}: gain out of range")
        if len(p["name"]) > NAME_LEN:
            raise ValueError(f"{p['id']}: name longer than {NAME_LEN}")
    return presets


def preset_by_id(pid):
    for p in load_presets():
        if p["id"] == pid:
            return p
    raise KeyError(f"unknown preset {pid!r}")


# ---------------------------------------------------------------------------
# Crush: quantise + sample-and-hold rate reduction
# ---------------------------------------------------------------------------

def gain_q8(percent):
    return percent * 256 // 100


def bits_mask(bits):
    return (0xFFFF << (16 - bits)) & 0xFFFF


def rate_step(rate, src_rate):
    """0.16 phase increment; 0 means latch every sample (no rate change)."""
    if rate == 0 or rate >= src_rate:
        return 0
    return (rate << 16) // src_rate


class CrushState:
    def __init__(self, bits, rate, gain, src_rate):
        self.mask = bits_mask(bits)
        self.gain = gain_q8(gain)
        self.step = rate_step(rate, src_rate)
        self.acc = 0xFFFF  # first sample always latches
        self.held = 0


def quantize(x, gain, mask):
    v = (x * gain) >> 8  # arithmetic shift, like SAR
    v = max(-32768, min(32767, v))
    v &= mask
    return v - 0x10000 if v & 0x8000 else v


def crush(samples, st, decimate=False):
    """Process int16 samples. hold mode keeps the length; decimate mode
    outputs only latched samples (for storing at the lower rate)."""
    out = []
    for x in samples:
        if st.step == 0:
            latch = True
        else:
            st.acc += st.step
            latch = st.acc > 0xFFFF
            st.acc &= 0xFFFF
        if latch:
            st.held = quantize(x, st.gain, st.mask)
            out.append(st.held)
        elif not decimate:
            out.append(st.held)
    return out


# ---------------------------------------------------------------------------
# Auto chop: streaming transient detector
# ---------------------------------------------------------------------------

class ChopState:
    """Envelope-follower onset detector. Keeps the `capacity` strongest
    onsets (exact streaming top-N), in time order.

    Envelopes are 16.16 fixed point, updated as  env += d * 2**(16 - k)
    with d = a - int(env), so a shift of k gives a time constant of about
    2**k samples. The fast envelope uses k_attack when rising and
    k_release when falling (peak follower). The slow envelope follows the
    fast one with k_slow, so a steady note settles at fast ~= slow and
    only a real jump in level triggers.
    """

    def __init__(self, capacity=16, k_attack=2, k_release=9, k_slow=11,
                 ratio_shift=1, thresh=300, min_gap=4410, zc_window=512):
        for k in (k_attack, k_release, k_slow):
            if not 2 <= k <= 15:
                raise ValueError("envelope shifts must be 2..15")
        self.capacity = capacity
        self.m_attack = 1 << (16 - k_attack)
        self.m_release = 1 << (16 - k_release)
        self.m_slow = 1 << (16 - k_slow)
        self.ratio_shift = ratio_shift
        self.thresh = thresh
        self.min_gap = min_gap
        self.zc_window = zc_window
        self.ef = self.es = 0  # 16.16
        self.gap = 0
        self.pos = 0
        self.last_zc = 0
        self.prev_neg = False
        self.onsets = []  # [(position, strength)]

    def add(self, pos, strength):
        if len(self.onsets) < self.capacity:
            self.onsets.append((pos, strength))
            return
        weakest = min(range(len(self.onsets)), key=lambda i: (self.onsets[i][1], i))
        if strength > self.onsets[weakest][1]:
            del self.onsets[weakest]
            self.onsets.append((pos, strength))


def detect(samples, st):
    for x in samples:
        neg = x < 0
        if neg != st.prev_neg:
            st.last_zc = st.pos
        st.prev_neg = neg
        a = abs(x) >> 1
        d = a - (st.ef >> 16)
        st.ef += d * (st.m_attack if d >= 0 else st.m_release)
        st.es += ((st.ef >> 16) - (st.es >> 16)) * st.m_slow
        if st.gap:
            st.gap -= 1
        else:
            fast, slow = st.ef >> 16, st.es >> 16
            s = fast - slow
            if s > (slow >> st.ratio_shift) + st.thresh:
                near = st.pos - st.last_zc <= st.zc_window
                st.add(st.last_zc if near else st.pos, s)
                st.gap = st.min_gap
        st.pos += 1
    return st.onsets


def slice_points(onsets, n, length):
    """Final slice starts: always includes 0, at most n slices."""
    points = sorted({0, *(p for p, _ in onsets)})
    if len(points) > n:
        strength = dict(onsets)
        keep = sorted(points[1:], key=lambda p: -strength.get(p, 0))[: n - 1]
        points = sorted([0, *keep])
    return [p for p in points if p < length]


def equal_slices(n, length):
    return [length * i // n for i in range(n)]


# ---------------------------------------------------------------------------
# WAV I/O
# ---------------------------------------------------------------------------

def read_wav(path):
    with wave.open(path, "rb") as w:
        if w.getsampwidth() != 2:
            raise SystemExit("only 16-bit PCM WAV is supported")
        ch, rate = w.getnchannels(), w.getframerate()
        data = array("h", w.readframes(w.getnframes()))
    if sys.byteorder == "big":
        data.byteswap()
    return [list(data[c::ch]) for c in range(ch)], rate


def write_wav(path, channels, rate):
    frames = array("h", [s for frame in zip(*channels) for s in frame])
    if sys.byteorder == "big":
        frames.byteswap()
    with wave.open(path, "wb") as w:
        w.setnchannels(len(channels))
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(frames.tobytes())


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def cmd_presets(_):
    for p in load_presets():
        rate = f"{p['rate']} Hz" if p["rate"] else "source rate"
        print(f"{p['id']:<8} {p['name']:<10} {p['bits']:2d}-bit  {rate:<12} gain {p['gain']}%")


def cmd_crush(args):
    p = preset_by_id(args.preset)
    chans, rate = read_wav(args.input)
    out = [crush(c, CrushState(p["bits"], p["rate"], p["gain"], rate), args.decimate) for c in chans]
    out_rate = p["rate"] if args.decimate and rate_step(p["rate"], rate) else rate
    write_wav(args.output, out, out_rate)
    print(f"{p['name']}: wrote {args.output} ({out_rate} Hz)")


def cmd_chop(args):
    chans, rate = read_wav(args.input)
    length = len(chans[0])
    if args.equal:
        points = equal_slices(args.slices, length)
    else:
        mono = [sum(f) // len(f) for f in zip(*chans)]
        st = ChopState(capacity=args.slices, thresh=args.thresh,
                       min_gap=int(rate * args.min_gap_ms / 1000))
        points = slice_points(detect(mono, st), args.slices, length)
    for i, p in enumerate(points):
        print(f"slice {i + 1:2d}  {p:9d}  {p / rate:8.3f}s")
    if args.outdir:
        os.makedirs(args.outdir, exist_ok=True)
        ends = points[1:] + [length]
        for i, (a, b) in enumerate(zip(points, ends)):
            write_wav(os.path.join(args.outdir, f"slice{i + 1:02d}.wav"), [c[a:b] for c in chans], rate)
        print(f"wrote {len(points)} slices to {args.outdir}")


def gen_inc():
    lines = [
        "; GENERATED by tools/vintage.py gen-inc from presets/vintage.toml -- do not edit.",
        ";",
        "; struc preset: name (10 bytes, space padded), bits (byte), pad (byte),",
        ";               rate (word, Hz, 0 = keep source rate), gain (word, Q8)",
        "",
        "PRESET_SIZE equ 16",
        "PRESET_NAME equ 0",
        "PRESET_BITS equ 10",
        "PRESET_RATE equ 12",
        "PRESET_GAIN equ 14",
        "",
    ]
    presets = load_presets()
    lines.append(f"PRESET_COUNT equ {len(presets)}")
    lines.append("")
    lines.append("preset_table:")
    for p in presets:
        name = p["name"].ljust(NAME_LEN)
        lines.append(f'    db "{name}", {p["bits"]}, 0')
        lines.append(f'    dw {p["rate"]}, {gain_q8(p["gain"])}    ; {p["id"]}')
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("presets").set_defaults(fn=cmd_presets)
    s = sub.add_parser("crush")
    s.add_argument("input")
    s.add_argument("output")
    s.add_argument("-p", "--preset", default="sp1200")
    s.add_argument("--decimate", action="store_true", help="store at the preset rate instead of holding")
    s.set_defaults(fn=cmd_crush)
    s = sub.add_parser("chop")
    s.add_argument("input")
    s.add_argument("-n", "--slices", type=int, default=16)
    s.add_argument("--equal", action="store_true", help="equal-length slices instead of transients")
    s.add_argument("--thresh", type=int, default=300)
    s.add_argument("--min-gap-ms", type=float, default=100)
    s.add_argument("-o", "--outdir")
    s.set_defaults(fn=cmd_chop)
    sub.add_parser("gen-inc").set_defaults(fn=lambda a: print(gen_inc(), end=""))
    args = ap.parse_args(argv)
    return args.fn(args) or 0


if __name__ == "__main__":
    sys.exit(main())
