"""Regression tests in the MAME test machine (docs/emulator.md).

Each test boots a real build of the S1100 OS in emu/bin/s1100fx, presses
front-panel keys, and reads the LCD back as text with the OS's own font.
They run when both emu/bin/s1100fx (emu/mame/build.sh) and Akai's
original/S11K-430.EXE exist, and are skipped otherwise.
"""

import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXE = os.path.join(ROOT, "original", "S11K-430.EXE")
sys.path.insert(0, os.path.join(ROOT, "tools"))

import s1100test  # noqa: E402

BOOT_SECONDS = 8
STOCK_BOOT_PAGE = [
    "PROGRAMS IN MEMORY (vol: NOT NAMED    )",
    "*  1 TEST PROGRAM     1 program(s)",
    "1 now active",
    "PROGRAM NUMBER   1",
    "DATA knob to select^",
    "<CURSOR knob to view",
    "SLCT RNUM MIX MIDI DISK DEL   FX",
]
# Pages reached from the boot page; patched builds must render them exactly
# as the stock OS does.
PAGES = ["KEY4:Disk", "KEY5:Master", "KEY0:Select Prog", "KEY3:MIDI"]


def tool(*args):
    subprocess.run([sys.executable, *args], cwd=ROOT, check=True, capture_output=True)


@unittest.skipUnless(s1100test.available(), "MAME test machine not built (emu/mame/build.sh)")
@unittest.skipUnless(os.path.exists(EXE), "original/S11K-430.EXE not present")
class MameRegressionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        t = lambda name: os.path.join(cls.tmp.name, name)  # noqa: E731
        cls.stock_img, stock_os = t("stock.img"), t("stock_os.bin")
        tool("tools/sxd2img.py", EXE, cls.stock_img)
        tool("tools/akaidisk.py", "get", cls.stock_img, "#0", stock_os)

        cls.banner_img, banner_os = t("banner.img"), t("banner_os.bin")
        tool("tools/patch.py", "--no-payload", stock_os, banner_os, "patches/s1100fx.toml", "mods/banner.toml")
        tool("tools/akaidisk.py", "put", cls.stock_img, "#0", banner_os, "--replace", "-o", cls.banner_img)

        cls.full_img, cls.full_os = t("full.img"), t("full_os.bin")
        tool("tools/patch.py", stock_os, cls.full_os, "patches/s1100fx.toml",
             "mods/banner.toml", "mods/vintage.toml", "mods/autochop.toml")
        tool("tools/akaidisk.py", "put", cls.stock_img, "#0", cls.full_os, "--replace", "-o", cls.full_img)
        with open(stock_os, "rb") as f:
            cls.stock_size = len(f.read())

        cls.runs = {}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def tour(self, img):
        """Boot page, then each page in PAGES (pressed one after another)."""
        if img not in self.runs:
            steps = s1100test.boot_steps(BOOT_SECONDS, PAGES)
            self.runs[img] = s1100test.run(steps, img)[0]
        return self.runs[img]

    def page(self, lcd):
        return list(lcd.lines().values())

    def test_stock_boots_to_programs_page(self):
        self.assertEqual(self.page(self.tour(self.stock_img)["boot"]), STOCK_BOOT_PAGE)

    def test_stock_disk_page_reads_floppy(self):
        disk = self.tour(self.stock_img)["press1"]
        self.assertTrue(disk.contains("LOAD FROM DISK"), disk.text())
        for name in ("TEST PROGRAM", "SINE", "SQUARE", "SAWTOOTH", "PULSE"):
            self.assertTrue(disk.contains(name), f"{name} missing:\n{disk.text()}")

    def test_banner_mod_title(self):
        page = self.page(self.tour(self.banner_img)["boot"])
        self.assertEqual(page[0], "S1100FX  PROGRAMS  (vol: NOT NAMED    )")
        self.assertEqual(page[1:], STOCK_BOOT_PAGE[1:])

    def test_banner_mod_changes_only_the_title(self):
        stock, banner = self.tour(self.stock_img)["boot"], self.tour(self.banner_img)["boot"]
        changed_rows = {y for _, y in stock.diff(banner)}
        self.assertTrue(changed_rows)
        self.assertLessEqual(max(changed_rows), 8, "pixels changed below the title line")

    def test_full_build_matches_banner_build_everywhere(self):
        banner, full = self.tour(self.banner_img), self.tour(self.full_img)
        self.assertEqual(sorted(banner), sorted(full))
        for name in banner:
            self.assertEqual(banner[name], full[name], f"screen '{name}' differs")

    def test_pages_unchanged_by_mods(self):
        stock, full = self.tour(self.stock_img), self.tour(self.full_img)
        for i in range(1, len(PAGES) + 1):
            name = f"press{i}"
            s, f = self.page(stock[name]), self.page(full[name])
            # the banner text is the only allowed difference
            f = [line.replace("S1100FX  PROGRAMS ", "PROGRAMS IN MEMORY") for line in f]
            self.assertEqual(s, f, f"{PAGES[i - 1]} page differs")

    def test_payload_copied_to_3000_aa80(self):
        with open(self.full_os, "rb") as f:
            payload = f.read()[self.stock_size:]
        addr = 0x30000 + (self.stock_size - 0x15460)
        steps = [f"wait {BOOT_SECONDS * s1100test.FRAMES_PER_SECOND}",
                 f"mem payload {addr} {len(payload)}"]
        _, mems, _ = s1100test.run(steps, self.full_img)
        self.assertEqual(mems["payload"], payload)


if __name__ == "__main__":
    unittest.main()
