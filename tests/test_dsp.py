"""Run the V50 DSP assembly in an x86-16 emulator and check it is
bit-exact with the Python reference model in tools/vintage.py."""

import math
import os
import random
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import vintage  # noqa: E402

try:
    import unicorn
    from unicorn import x86_const as R
except ImportError:  # pragma: no cover
    unicorn = None

CODE_SEG, DATA_SEG, OUT_SEG, STACK_SEG = 0x1000, 0x2000, 0x3000, 0x7000
STATE, LIST, IN_BUF = 0x0000, 0x0100, 0x1000  # offsets in DATA_SEG
MAX_CHUNK = (0x10000 - IN_BUF) // 2

HARNESS = """
bits 16
cpu 186
org 0
    jmp near crush_setup        ; 0
    jmp near crush_process      ; 3
    jmp near chop_process       ; 6
stop:
    hlt                         ; 9
%include "presets.inc"
%include "crush.asm"
%include "chop.asm"
"""
V_SETUP, V_CRUSH, V_CHOP, STOP = 0, 3, 6, 9


def assemble():
    with tempfile.TemporaryDirectory() as tmp:
        src, out = os.path.join(tmp, "h.asm"), os.path.join(tmp, "h.bin")
        with open(src, "w") as f:
            f.write(HARNESS)
        subprocess.run(["nasm", "-f", "bin", "-I", os.path.join(ROOT, "src", "dsp") + "/",
                        "-l", os.path.join(tmp, "h.lst"), "-o", out, src], check=True)
        with open(out, "rb") as f:
            code = f.read()
        with open(os.path.join(tmp, "h.lst")) as f:
            lst = f.read()
    return code, lst


def preset_table_offset(code):
    """Offset of preset_table in the harness, found by its first preset name."""
    first = vintage.load_presets()[0]["name"].ljust(vintage.NAME_LEN).encode()
    return code.index(first)


class V50:
    def __init__(self, code):
        self.mu = unicorn.Uc(unicorn.UC_ARCH_X86, unicorn.UC_MODE_16)
        self.mu.mem_map(0, 0x100000)
        self.mu.mem_write(CODE_SEG * 16, code)

    def lin(self, seg, off):
        return seg * 16 + off

    def write_words(self, seg, off, words):
        self.mu.mem_write(self.lin(seg, off), struct.pack(f"<{len(words)}h", *words))

    def read_words(self, seg, off, n, fmt="h"):
        return list(struct.unpack(f"<{n}{fmt}", self.mu.mem_read(self.lin(seg, off), 2 * n)))

    def call(self, vector, **regs):
        mu = self.mu
        mu.reg_write(R.UC_X86_REG_SS, STACK_SEG)
        mu.reg_write(R.UC_X86_REG_SP, 0xFFFE - 2)
        mu.mem_write(self.lin(STACK_SEG, 0xFFFE - 2), struct.pack("<H", STOP))
        mu.reg_write(R.UC_X86_REG_CS, CODE_SEG)
        mu.reg_write(R.UC_X86_REG_DS, DATA_SEG)
        mu.reg_write(R.UC_X86_REG_ES, OUT_SEG)
        sentinel = {"BP": 0xB00B, "BX": STATE}
        for name, val in {**sentinel, **regs}.items():
            mu.reg_write(getattr(R, f"UC_X86_REG_{name}"), val)
        mu.emu_start(self.lin(CODE_SEG, vector), self.lin(CODE_SEG, STOP))
        assert mu.reg_read(R.UC_X86_REG_BP) == sentinel["BP"], "BP not preserved"
        assert mu.reg_read(R.UC_X86_REG_BX) == regs.get("BX", STATE), "BX not preserved"
        return {n: mu.reg_read(getattr(R, f"UC_X86_REG_{n}")) for n in ("AX", "CX", "SI", "DI")}


def test_signal(n, rate=44100, seed=1):
    """Drum-ish test signal: decaying tone bursts over noise, plus clipping
    extremes so saturation paths are exercised."""
    rng = random.Random(seed)
    out = []
    hits = {int(rate * t) for t in (0.05, 0.31, 0.52, 0.77, 0.9, 1.21, 1.4)}
    env, freq = 0.0, 100.0
    for i in range(n):
        if i in hits:
            env, freq = 1.0, rng.choice((60, 180, 900))
        env *= 0.9995
        v = env * 40000 * math.sin(2 * math.pi * freq * i / rate) + rng.gauss(0, 150)
        out.append(max(-32768, min(32767, int(v))))
    out[100:104] = [32767, -32768, 32767, -32768]
    return out


@unittest.skipIf(unicorn is None, "pip install unicorn to run emulator tests")
class DSPTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.code, _ = assemble()
        cls.table = preset_table_offset(cls.code)

    def setUp(self):
        self.cpu = V50(self.code)

    # -- crush ----------------------------------------------------------
    def run_crush(self, preset_index, samples, src_rate, decimate=False, chunks=(4096,)):
        cpu = self.cpu
        cpu.mu.mem_write(cpu.lin(DATA_SEG, STATE), bytes(16))
        cpu.mu.mem_write(cpu.lin(DATA_SEG, STATE + 10), bytes([1 if decimate else 0]))
        # Preset table lives in CODE_SEG; copy the entry next to the state.
        entry = self.code[self.table + 16 * preset_index: self.table + 16 * (preset_index + 1)]
        cpu.mu.mem_write(cpu.lin(DATA_SEG, LIST), entry)
        cpu.call(V_SETUP, SI=LIST, AX=src_rate)
        out, pos, k = [], 0, 0
        while pos < len(samples):
            n = min(chunks[k % len(chunks)], len(samples) - pos, MAX_CHUNK)
            k += 1
            cpu.write_words(DATA_SEG, IN_BUF, samples[pos:pos + n])
            r = cpu.call(V_CRUSH, SI=IN_BUF, DI=0, CX=n)
            self.assertEqual(r["CX"], 0)
            self.assertEqual(r["SI"], IN_BUF + 2 * n)
            self.assertEqual(r["DI"], 2 * r["AX"])
            out += cpu.read_words(OUT_SEG, 0, r["AX"])
            pos += n
        return out

    def test_crush_all_presets_bit_exact(self):
        samples = test_signal(6000)
        for i, p in enumerate(vintage.load_presets()):
            for src in (44100, 22050):
                for decimate in (False, True):
                    with self.subTest(preset=p["id"], src=src, decimate=decimate):
                        st = vintage.CrushState(p["bits"], p["rate"], p["gain"], src)
                        want = vintage.crush(samples, st, decimate)
                        got = self.run_crush(i, samples, src, decimate, chunks=(1000, 7, 1, 333))
                        self.assertEqual(got, want)

    def test_crush_output_properties(self):
        presets = vintage.load_presets()
        i = next(k for k, p in enumerate(presets) if p["id"] == "sp1200")
        samples = test_signal(4000)
        out = self.run_crush(i, samples, 44100)
        self.assertEqual(len(out), len(samples))
        self.assertTrue(all(v % 16 == 0 for v in out), "not 12-bit")
        dec = self.run_crush(i, samples, 44100, decimate=True)
        self.assertAlmostEqual(len(dec) / len(samples), 26040 / 44100, places=2)

    def test_crush_zero_count(self):
        self.cpu.mu.mem_write(self.cpu.lin(DATA_SEG, LIST), self.code[self.table:self.table + 16])
        self.cpu.call(V_SETUP, SI=LIST, AX=44100)
        r = self.cpu.call(V_CRUSH, SI=IN_BUF, DI=0, CX=0)
        self.assertEqual(r["AX"], 0)

    # -- chop -----------------------------------------------------------
    def run_chop(self, samples, st, chunks=(4096,)):
        cpu = self.cpu
        state = struct.pack("<iiHHHBBhHHHIIHHH", 0, 0, st.m_attack, st.m_release, st.m_slow,
                            st.ratio_shift, 0, st.thresh, 0, st.min_gap, st.zc_window, 0, 0,
                            st.capacity, 0, LIST)
        self.assertEqual(len(state), 38)
        cpu.mu.mem_write(cpu.lin(DATA_SEG, STATE), state)
        pos, k = 0, 0
        while pos < len(samples):
            n = min(chunks[k % len(chunks)], len(samples) - pos, MAX_CHUNK)
            k += 1
            cpu.write_words(DATA_SEG, IN_BUF, samples[pos:pos + n])
            cpu.call(V_CHOP, SI=IN_BUF, CX=n)
            pos += n
        count = cpu.read_words(DATA_SEG, STATE + 34, 1, "H")[0]
        raw = cpu.mu.mem_read(cpu.lin(DATA_SEG, LIST), 6 * count)
        return [struct.unpack_from("<Ih", raw, 6 * i) for i in range(count)]

    def test_chop_bit_exact(self):
        samples = test_signal(70000)  # > 64K samples: exercises 32-bit positions
        for cap, thresh, gap in ((16, 300, 4410), (3, 300, 2000), (8, 50, 500), (1, 300, 100)):
            with self.subTest(capacity=cap, thresh=thresh, gap=gap):
                kw = dict(capacity=cap, thresh=thresh, min_gap=gap)
                want = vintage.detect(samples, vintage.ChopState(**kw))
                got = self.run_chop(samples, vintage.ChopState(**kw), chunks=(5000, 1, 4097))
                self.assertEqual(got, [tuple(o) for o in want])

    def test_chop_finds_hits(self):
        rate = 44100
        samples = test_signal(70000)
        samples[100:104] = [0] * 4  # the clipping glitch is itself a transient
        onsets = vintage.detect(samples, vintage.ChopState(capacity=16))
        points = vintage.slice_points(onsets, 16, len(samples))
        hits = [int(rate * t) for t in (0.05, 0.31, 0.52, 0.77, 0.9, 1.21, 1.4)]
        for h in hits:
            self.assertTrue(any(-600 <= p - h <= 300 for p in points), f"hit at {h} missed: {points}")
        self.assertEqual(len(points), len(hits) + 1, f"false positives: {points}")

    def test_chop_ignores_sustained_notes(self):
        for amp in (800, 20000, 32000):
            for freq in (40, 200, 2000):
                with self.subTest(amp=amp, freq=freq):
                    tone = [int(amp * math.sin(2 * math.pi * freq * i / 44100)) for i in range(44100)]
                    self.assertEqual(len(vintage.detect(tone, vintage.ChopState())), 1)


class ModelTest(unittest.TestCase):
    def test_quantize(self):
        mask = vintage.bits_mask(12)
        self.assertEqual(vintage.quantize(17, 256, mask), 16)
        self.assertEqual(vintage.quantize(-1, 256, mask), -16)  # floor, like SAR
        self.assertEqual(vintage.quantize(30000, 512, mask), 32752)  # clips
        self.assertEqual(vintage.quantize(-30000, 512, mask), -32768)

    def test_equal_slices_and_points(self):
        self.assertEqual(vintage.equal_slices(4, 100), [0, 25, 50, 75])
        onsets = [(10, 5), (20, 50), (30, 1)]
        self.assertEqual(vintage.slice_points(onsets, 3, 100), [0, 10, 20])

    def test_inc_in_sync(self):
        with open(os.path.join(ROOT, "src", "dsp", "presets.inc")) as f:
            self.assertEqual(f.read(), vintage.gen_inc(),
                             "run: python3 tools/vintage.py gen-inc > src/dsp/presets.inc")


if __name__ == "__main__":
    unittest.main()
