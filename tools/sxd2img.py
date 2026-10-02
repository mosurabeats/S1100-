#!/usr/bin/env python3
"""Extract the floppy image from an Akai OS-update EXE (Sydex self-
extracting disk, "SXD"), e.g. S11K-430.EXE / S1K-440.EXE.

Akai distributed OS updates as DOS programs that write an Akai-format disk
on a PC floppy drive. Rather than reimplement the compressed format, this
runs the original program in a minimal DOS/BIOS emulator (Unicorn) and
records every sector it writes through INT 13h, then assembles them into a
raw .img for akaidisk.py / a Gotek.

    python3 tools/sxd2img.py S11K-430.EXE original/S1100_OS.img
"""

import argparse
import struct
import sys

import unicorn
from unicorn import x86_const as R

PSP_SEG = 0x0800
ENV_SEG = 0x0700
MEM_TOP_SEG = 0xA000
DPT_ADDR = 0x0522  # BIOS diskette parameter table location (vector 1Eh)
STOP_ADDR = 0xF0000


class DOSExit(Exception):
    pass


class Machine:
    def __init__(self, exe_path, verbose=False, keys=b"\r" * 64):
        with open(exe_path, "rb") as f:
            self.exe = f.read()
        self.path = exe_path
        self.verbose = verbose
        self.keys = bytearray(keys)
        self.mu = unicorn.Uc(unicorn.UC_ARCH_X86, unicorn.UC_MODE_16)
        self.mu.mem_map(0, 0x100000)
        self.files = {}
        self.next_handle = 5
        self.sectors = {}
        self.geometry = None
        self.output = bytearray()
        self.alloc_next = None
        self.unhandled = []
        self.load()

    # --- memory helpers -------------------------------------------------
    def reg(self, name):
        return self.mu.reg_read(getattr(R, f"UC_X86_REG_{name}"))

    def set(self, name, val):
        self.mu.reg_write(getattr(R, f"UC_X86_REG_{name}"), val)

    def rd(self, seg, off, n):
        return bytes(self.mu.mem_read(seg * 16 + off, n))

    def wr(self, seg, off, data):
        self.mu.mem_write(seg * 16 + off, bytes(data))

    def asciiz(self, seg, off):
        out = bytearray()
        while True:
            b = self.rd(seg, off + len(out), 1)[0]
            if b == 0:
                return out.decode("latin-1")
            out.append(b)

    def set_carry(self, on):
        fl = self.reg("EFLAGS")
        self.set("EFLAGS", fl | 1 if on else fl & ~1)

    # --- loading --------------------------------------------------------
    def load(self):
        e = self.exe
        last, pages, nrel, hdr_paras = struct.unpack_from("<HHHH", e, 2)
        ss, sp, _, ip, cs, rel_off = struct.unpack_from("<HHHHHH", e, 0x0E)
        size = (pages - 1) * 512 + (last or 512)
        image = e[hdr_paras * 16:size]
        load_seg = PSP_SEG + 0x10
        self.wr(load_seg, 0, image)
        for i in range(nrel):
            off, seg = struct.unpack_from("<HH", e, rel_off + 4 * i)
            addr = (load_seg + seg) * 16 + off
            v = struct.unpack("<H", self.mu.mem_read(addr, 2))[0]
            self.mu.mem_write(addr, struct.pack("<H", (v + load_seg) & 0xFFFF))
        # PSP
        psp = bytearray(256)
        psp[0:2] = b"\xcd\x20"
        struct.pack_into("<H", psp, 2, MEM_TOP_SEG)
        struct.pack_into("<H", psp, 0x2C, ENV_SEG)
        psp[0x80] = 0
        psp[0x81] = 0x0D
        self.wr(PSP_SEG, 0, psp)
        env = b"PATH=A:\\\0COMSPEC=A:\\COMMAND.COM\0\0\x01\0A:\\" + \
            self.path.rsplit("/", 1)[-1].upper().encode() + b"\0"
        self.wr(ENV_SEG, 0, env)
        # Every interrupt vector points at an `int n; iret`-free stub: we
        # handle INT via the hook, so vectors just need to be distinct.
        for n in range(256):
            self.wr(0, n * 4, struct.pack("<HH", n, 0xF000))
        self.wr(0xF000, 0, b"\xcf" * 256)  # IRET
        # Diskette parameter table (vector 1Eh)
        self.wr(0, DPT_ADDR, bytes([0xDF, 0x02, 0x25, 0x02, 18, 0x1B, 0xFF, 0x54, 0xF6, 0x0F, 0x08]))
        self.wr(0, 0x1E * 4, struct.pack("<HH", DPT_ADDR, 0))
        # BIOS data area: equipment word -> one floppy, 80x25 colour
        self.wr(0x40, 0x10, struct.pack("<H", 0x0021))
        self.wr(0x40, 0x13, struct.pack("<H", 640))
        self.alloc_next = load_seg + (len(image) + 15) // 16 + 0x1000
        self.set("SS", (load_seg + ss) & 0xFFFF)
        self.set("SP", sp)
        self.set("DS", PSP_SEG)
        self.set("ES", PSP_SEG)
        self.set("CS", (load_seg + cs) & 0xFFFF)
        self.set("IP", ip)
        self.mu.hook_add(unicorn.UC_HOOK_INTR, self.on_int)
        self.mu.hook_add(unicorn.UC_HOOK_INSN, self.on_in, None, 1, 0, R.UC_X86_INS_IN)
        self.mu.hook_add(unicorn.UC_HOOK_INSN, self.on_out, None, 1, 0, R.UC_X86_INS_OUT)

    def run(self, max_insns=2_000_000_000):
        start = self.reg("CS") * 16 + self.reg("IP")
        try:
            self.mu.emu_start(start, STOP_ADDR, count=max_insns)
        except DOSExit:
            pass

    # --- port I/O -----------------------------------------------------------
    def on_in(self, mu, port, size, _):
        if self.verbose:
            print(f"  in  port 0x{port:x}", file=sys.stderr)
        if port == 0x3F4:  # FDC main status: ready
            return 0x80
        return 0

    def on_out(self, mu, port, size, value, _):
        if self.verbose:
            print(f"  out port 0x{port:x} = 0x{value:x}", file=sys.stderr)

    # --- interrupts -----------------------------------------------------------
    def on_int(self, mu, intno, _):
        ah = self.reg("AH")
        h = getattr(self, f"int_{intno:02x}", None)
        if self.verbose:
            print(f"INT {intno:02x} AH={ah:02x} AX={self.reg('AX'):04x} at "
                  f"{self.reg('CS'):04x}:{self.reg('IP'):04x}", file=sys.stderr)
        if h is None or not h(ah):
            self.unhandled.append((intno, ah))
            if self.verbose:
                print(f"  unhandled INT {intno:02x}/{ah:02x}", file=sys.stderr)

    def int_20(self, ah):
        raise DOSExit()

    def int_10(self, ah):
        if ah == 0x0E:
            self.output.append(self.reg("AL"))
        elif ah == 0x0F:
            self.set("AX", 0x5003)
            self.set("BH", 0)
        elif ah == 0x03:
            self.set("DX", 0)
            self.set("CX", 0x0607)
        return True

    def int_11(self, ah):
        self.set("AX", 0x0021)
        return True

    def int_12(self, ah):
        self.set("AX", 640)
        return True

    def int_16(self, ah):
        if ah in (0x00, 0x10):
            k = self.keys.pop(0) if self.keys else 0x0D
            self.set("AX", k)
        elif ah in (0x01, 0x11):
            fl = self.reg("EFLAGS")
            self.set("EFLAGS", fl & ~0x40 if self.keys else fl | 0x40)
            if self.keys:
                self.set("AX", self.keys[0])
        elif ah == 0x02:
            self.set("AL", 0)
        return True

    def int_1a(self, ah):
        if ah == 0x00:
            self.ticks = getattr(self, "ticks", 0) + 1
            self.set("CX", 0)
            self.set("DX", self.ticks & 0xFFFF)
        return True

    def int_13(self, ah):
        dl = self.reg("DL")
        if ah == 0x00:  # reset
            self.set("AH", 0)
            self.set_carry(False)
            return True
        if ah == 0x08:  # drive params: 1.44M 3.5"
            self.set("AX", 0)
            self.set("BX", 0x0004)
            self.set("CX", 0x4F12)
            self.set("DX", 0x0101)
            self.set("ES", 0)
            self.set("DI", DPT_ADDR)
            self.set_carry(False)
            return True
        if ah == 0x15:  # drive type: floppy with change line
            self.set("AH", 0x02)
            self.set_carry(False)
            return True
        if ah == 0x16:  # disk change status: not changed
            self.set("AH", 0)
            self.set_carry(False)
            return True
        if ah == 0x17 or ah == 0x18:  # set media type
            self.set("AH", 0)
            self.set_carry(False)
            return True
        if ah in (0x02, 0x03, 0x04, 0x05):
            al, ch, cl, dh = self.reg("AL"), self.reg("CH"), self.reg("CL"), self.reg("DH")
            cyl = ch | ((cl & 0xC0) << 2)
            sec = cl & 0x3F
            es, bx = self.reg("ES"), self.reg("BX")
            dpt_seg, dpt_off = struct.unpack("<HH", self.rd(0, 0x1E * 4, 4))[::-1]
            size_code = self.rd(dpt_seg, dpt_off + 3, 1)[0]
            ssize = 128 << size_code
            if ah == 0x05:  # format: record the track's sector IDs
                ids = self.rd(es, bx, 4 * 64)
                fmt = [tuple(ids[i:i + 4]) for i in range(0, 4 * al, 4)] if al else []
                self.formats = getattr(self, "formats", [])
                self.formats.append((cyl, dh, al, fmt))
            elif ah == 0x03:
                for i in range(al):
                    self.sectors[(cyl, dh, sec + i)] = self.rd(es, bx + i * ssize, ssize)
            elif ah == 0x02:
                for i in range(al):
                    data = self.sectors.get((cyl, dh, sec + i), bytes(ssize))
                    self.wr(es, bx + i * ssize, data)
            self.ssize = ssize
            self.set("AH", 0)
            self.set_carry(False)
            return True
        return False

    def int_21(self, ah):
        al = self.reg("AL")
        ds, dx = self.reg("DS"), self.reg("DX")
        ok = lambda: self.set_carry(False)  # noqa: E731
        if ah == 0x30:
            self.set("AX", 0x1606)  # DOS 6.22
            self.set("BX", 0)
            return True
        if ah in (0x02, 0x06) and not (ah == 0x06 and self.reg("DL") == 0xFF):
            self.output.append(self.reg("DL"))
            return True
        if ah == 0x06:
            self.set("AL", self.keys.pop(0) if self.keys else 0)
            return True
        if ah in (0x01, 0x07, 0x08):
            self.set("AL", self.keys.pop(0) if self.keys else 0x0D)
            return True
        if ah == 0x0B:
            self.set("AL", 0xFF if self.keys else 0)
            return True
        if ah == 0x0C:
            return self.int_21(al) if al in (0x01, 0x06, 0x07, 0x08) else True
        if ah == 0x09:
            s = bytearray()
            while True:
                b = self.rd(ds, dx + len(s), 1)[0]
                if b == ord("$"):
                    break
                s.append(b)
            self.output += s
            return True
        if ah == 0x40:
            n = self.reg("CX")
            data = self.rd(ds, dx, n)
            bx = self.reg("BX")
            if bx in (1, 2):
                self.output += data
            self.set("AX", n)
            ok()
            return True
        if ah == 0x25:
            self.wr(0, al * 4, struct.pack("<HH", dx, ds))
            return True
        if ah == 0x35:
            off, seg = struct.unpack("<HH", self.rd(0, al * 4, 4))
            self.set("ES", seg)
            self.set("BX", off)
            return True
        if ah == 0x4A:
            ok()
            return True
        if ah == 0x48:
            seg = self.alloc_next
            self.alloc_next += self.reg("BX") + 1
            if self.alloc_next > MEM_TOP_SEG:
                self.set("AX", 8)
                self.set("BX", max(0, MEM_TOP_SEG - seg - 1))
                self.set_carry(True)
                self.alloc_next = seg
                return True
            self.set("AX", seg)
            ok()
            return True
        if ah == 0x49:
            ok()
            return True
        if ah == 0x3D:
            name = self.asciiz(ds, dx)
            h = self.next_handle
            self.next_handle += 1
            self.files[h] = [self.exe, 0]
            if self.verbose:
                print(f"  open {name!r} -> {h}", file=sys.stderr)
            self.set("AX", h)
            ok()
            return True
        if ah == 0x3F:
            f = self.files.get(self.reg("BX"))
            if f is None:
                self.set("AX", 6)
                self.set_carry(True)
                return True
            n = self.reg("CX")
            data = f[0][f[1]:f[1] + n]
            f[1] += len(data)
            self.wr(ds, dx, data)
            self.set("AX", len(data))
            ok()
            return True
        if ah == 0x42:
            f = self.files[self.reg("BX")]
            off = (self.reg("CX") << 16) | dx
            if off & 0x80000000:
                off -= 1 << 32
            base = (0, f[1], len(f[0]))[al]
            f[1] = base + off
            self.set("DX", f[1] >> 16)
            self.set("AX", f[1] & 0xFFFF)
            ok()
            return True
        if ah == 0x3E:
            self.files.pop(self.reg("BX"), None)
            ok()
            return True
        if ah == 0x44:
            if al == 0x00:
                self.set("DX", 0x80 | 0x03 if self.reg("BX") < 3 else 0)
            elif al == 0x08:
                self.set("AX", 0)
            ok()
            return True
        if ah == 0x19:
            self.set("AL", 2)
            return True
        if ah == 0x0E:
            self.set("AL", 3)
            return True
        if ah == 0x2A:
            self.set("CX", 1998)
            self.set("DX", 0x0101)
            self.set("AL", 4)
            return True
        if ah == 0x2C:
            self.set("CX", 0)
            self.set("DX", 0)
            return True
        if ah == 0x62:
            self.set("BX", PSP_SEG)
            return True
        if ah == 0x33:
            self.set("DL", 0)
            return True
        if ah == 0x4C:
            raise DOSExit()
        return False

    # --- result -----------------------------------------------------------
    def image(self):
        if not self.sectors:
            raise SystemExit("program wrote no sectors")
        cyls = max(c for c, _, _ in self.sectors) + 1
        heads = max(h for _, h, _ in self.sectors) + 1
        spt = max(s for _, _, s in self.sectors)
        ssize = len(next(iter(self.sectors.values())))
        out = bytearray()
        for c in range(cyls):
            for h in range(heads):
                for s in range(1, spt + 1):
                    out += self.sectors.get((c, h, s), bytes(ssize))
        return bytes(out), (cyls, heads, spt, ssize)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("exe")
    ap.add_argument("out")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--cylinders", type=int, default=80,
                    help="pad the image to this many cylinders (Akai disks: 80)")
    args = ap.parse_args(argv)
    m = Machine(args.exe, args.verbose)
    m.run()
    text = m.output.decode("latin-1", "replace")
    if args.verbose:
        print(text, file=sys.stderr)
    if m.unhandled:
        print("unhandled interrupts:", sorted(set(m.unhandled)), file=sys.stderr)
    img, (c, h, s, ss) = m.image()
    full = args.cylinders * h * s * ss
    img = img.ljust(full, b"\0")
    with open(args.out, "wb") as f:
        f.write(img)
    print(f"wrote {args.out}: {len(img)} bytes ({max(c, args.cylinders)} cyl x {h} heads x "
          f"{s} sectors x {ss} bytes; {len(m.sectors)} sectors written)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
