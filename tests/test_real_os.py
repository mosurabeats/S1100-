"""End-to-end checks against Akai's real S1100 v4.30 OS update.

Akai's code is not in the repository, so these run only when
original/S11K-430.EXE is present (see README).
"""

import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXE = os.path.join(ROOT, "original", "S11K-430.EXE")
sys.path.insert(0, os.path.join(ROOT, "tools"))


def run(*args):
    return subprocess.run([sys.executable, *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout


@unittest.skipUnless(os.path.exists(EXE), "original/S11K-430.EXE not present")
class RealOSTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        t = cls.tmp.name
        cls.img = os.path.join(t, "stock.img")
        cls.os_bin = os.path.join(t, "stock_os.bin")
        cls.out = os.path.join(t, "fx_os.bin")
        run("tools/sxd2img.py", EXE, cls.img)
        run("tools/akaidisk.py", "get", cls.img, "#0", cls.os_bin)
        run("tools/patch.py", cls.os_bin, cls.out, "patches/s1100fx.toml",
            "mods/banner.toml", "mods/vintage.toml", "mods/autochop.toml")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_disk_format(self):
        self.assertIn("consistent", run("tools/akaidisk.py", "probe", self.img))

    def test_spec_matches_os(self):
        import hashlib
        import tomllib
        with open(os.path.join(ROOT, "patches", "s1100fx.toml"), "rb") as f:
            spec = tomllib.load(f)
        with open(self.os_bin, "rb") as f:
            self.assertEqual(hashlib.sha256(f.read()).hexdigest(), spec["base"]["sha256"])

    def test_patched_os_boots_like_stock(self):
        out = run("tools/s1100emu.py", self.out, "--compare", self.os_bin)
        self.assertIn("OK: boots to the same point as stock", out)
        self.assertIn("payload", out)

    def test_image_roundtrip_contiguous(self):
        import akaidisk
        img = os.path.join(self.tmp.name, "fx.img")
        run("tools/akaidisk.py", "put", self.img, "#0", self.out, "--replace", "-o", img)
        d = akaidisk.AkaiFloppy.load(img)
        self.assertEqual(d.check(), [])
        for e in d.entries():
            if e.used:
                self.assertTrue(d.contiguous(e), e.name)
        with open(self.out, "rb") as f:
            self.assertEqual(d.read_file(d.find("#0")), f.read())


if __name__ == "__main__":
    unittest.main()
