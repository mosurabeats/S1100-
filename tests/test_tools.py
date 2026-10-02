import os
import sys
import tempfile
import tomllib
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import akaidisk  # noqa: E402
import patch  # noqa: E402

EOF = 0xC000
SYS = 0x4000


def blank_hd():
    d = akaidisk.AkaiFloppy(bytes(1638400))
    for b in range(5):  # header blocks
        d.set_fat(b, SYS)
    return d


class AkaiDiskTest(unittest.TestCase):
    def test_charset_roundtrip(self):
        raw = akaidisk.akai_encode("S1100 OS")
        self.assertEqual(len(raw), 12)
        self.assertEqual(akaidisk.akai_decode(raw).rstrip(), "S1100 OS")
        with self.assertRaises(ValueError):
            akaidisk.akai_encode("a_b")

    def test_put_get_replace(self):
        d = blank_hd()
        payload = bytes(range(256)) * 20 + b"tail"
        d.put("S1100 OS", payload, 0x63, osver=0x0440, eof_code=EOF)
        self.assertEqual(d.check(), [])
        e = d.find("s1100 os")
        self.assertEqual(d.read_file(e), payload)
        self.assertEqual(d.observed_codes(), ({EOF: 1}, {SYS: 5}))

        # replace infers the EOF code from the image, keeps type/osver
        bigger = payload * 3
        e2 = d.replace("S1100 OS", bigger)
        self.assertEqual(d.read_file(e2), bigger)
        self.assertEqual((e2.type, e2.osver), (0x63, 0x0440))
        self.assertEqual(d.check(), [])

    def test_detects_corruption(self):
        d = blank_hd()
        e = d.put("A", b"x" * 3000, 1, eof_code=EOF)
        blocks = d.chain(e.start, e.size)
        d.set_fat(blocks[1], 0)
        self.assertTrue(d.check())

    def test_rejects_bad_size(self):
        with self.assertRaises(akaidisk.DiskError):
            akaidisk.AkaiFloppy(bytes(1474560))


class PatchTest(unittest.TestCase):
    OS = b"\x90" * 32 + b"AKAI S1100 V4.40" + b"\xe8\x10\x00" + b"\x90" * 13

    def build(self, toml_text, os_data=None):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "fx.asm"), "w") as f:
                f.write("bits 16\ncpu 186\norg PAYLOAD_OFF\nentry: jmp near entry\ndb 'FX'\n")
            spec = tomllib.loads(toml_text)
            return patch.build(spec, os_data or self.OS, tmp)

    def test_text_offset_asm_and_payload(self):
        out, _ = self.build("""
[payload]
source = "fx.asm"
[[patch]]
name = "banner"
find_text = "S1100"
replace_text = "S11FX"
[[patch]]
name = "hook"
offset = 48
expect = "e8 10 00"
asm = "call PAYLOAD_OFF"
""")
        self.assertIn(b"AKAI S11FX V4.40", out)
        # call rel16 from 48 to 64: e8 + (64 - 51)
        self.assertEqual(out[48:51], bytes([0xE8, 13, 0]))
        self.assertEqual(out[64:69], b"\xe9\xfd\xffFX")

    def test_expect_mismatch_fails(self):
        with self.assertRaisesRegex(patch.PatchError, "expected"):
            self.build('[[patch]]\nname="x"\noffset=0\nexpect="00"\nreplace="01"\n')

    def test_missing_text_suggests(self):
        with self.assertRaisesRegex(patch.PatchError, "AKAI S1100"):
            self.build('[[patch]]\nname="x"\nfind_text="S1100 OS"\nreplace_text="S1100 FX"\n')

    def test_386_rejected(self):
        with self.assertRaisesRegex(patch.PatchError, "nasm failed"):
            self.build('[[patch]]\nname="x"\noffset=0\nexpect="90"\nasm="mov eax, 1"\n')

    def test_mods_merge_and_define(self):
        base = tomllib.loads('[payload]\nsource = "fx.asm"\n')
        mod = tomllib.loads('[defines]\nMOD_X = 1\n[[patch]]\nname="b"\nfind_text="S1100"\nreplace_text="S11FX"\n')
        spec = patch.merge_specs([base, mod])
        self.assertEqual(spec["defines"], {"MOD_X": 1})
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "fx.asm"), "w") as f:
                f.write("bits 16\ncpu 186\norg PAYLOAD_OFF\n%ifdef MOD_X\ndb 'X'\n%endif\n")
            out, _ = patch.build(spec, self.OS, tmp)
        self.assertTrue(out.endswith(b"X"))
        self.assertIn(b"S11FX", out)
        with self.assertRaisesRegex(patch.PatchError, "may not set"):
            patch.merge_specs([base, base])
        with self.assertRaisesRegex(patch.PatchError, "duplicate"):
            patch.merge_specs([base, mod, mod])

    def test_sha_guard(self):
        with self.assertRaisesRegex(patch.PatchError, "sha256"):
            self.build('[base]\nsha256="00"\n')


if __name__ == "__main__":
    unittest.main()
