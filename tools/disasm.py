#!/usr/bin/env python3
"""Reverse-engineering helpers for the S1100 OS (NEC V50 = 8086/80186 code).

  strings  BIN                 printable strings (ASCII and Akai charset)
  dis      BIN START LEN       disassemble; --org sets the runtime offset
  io       BIN                 every IN/OUT with an immediate port, grouped
                               by port -- the fastest way to map hardware
  xref     BIN VALUE           instructions whose immediate/displacement
                               equals VALUE (e.g. the offset of a string)
  calls    BIN TARGET          near CALL/JMP instructions that land on TARGET

Linear-sweep disassembly over a whole binary will also decode data as
code; treat `io`/`xref` hits as leads to check with `dis`, not facts.
"""

import argparse
import re
import sys
from collections import defaultdict

import capstone
from capstone import x86

sys.path.insert(0, __import__("os").path.dirname(__file__))
from akaidisk import AKAI_CHARS  # noqa: E402


def load(path):
    with open(path, "rb") as f:
        return f.read()


def disasm(data, start=0, length=None, org=None):
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_16)
    md.detail = True
    md.skipdata = True
    end = len(data) if length is None else start + length
    base = start if org is None else org
    return md.disasm(data[start:end], base)


def cmd_strings(args):
    data = load(args.bin)
    for m in re.finditer(rb"[\x20-\x7e]{%d,}" % args.min, data):
        print(f"0x{m.start():06x} A {m.group().decode()!r}")
    # Akai charset: bytes 0..40; demand at least one letter to cut noise.
    run = bytearray()
    for i, b in enumerate(data + b"\xff"):
        if b < len(AKAI_CHARS):
            run.append(b)
            continue
        if len(run) >= args.min:
            s = "".join(AKAI_CHARS[c] for c in run)
            if sum(c.isalpha() for c in s) >= args.min - 1:
                print(f"0x{i - len(run):06x} K {s!r}")
        run.clear()


def cmd_dis(args):
    data = load(args.bin)
    for ins in disasm(data, args.start, args.len, args.org):
        print(f"{ins.address:06x}  {ins.bytes.hex(' '):<20} {ins.mnemonic} {ins.op_str}")


def cmd_io(args):
    data = load(args.bin)
    ports = defaultdict(list)
    for ins in disasm(data):
        if ins.mnemonic in ("in", "out") and ins.id != 0:
            for op in ins.operands:
                if op.type == x86.X86_OP_IMM:
                    ports[op.imm].append(f"0x{ins.address:06x} {ins.mnemonic} {ins.op_str}")
    for port in sorted(ports):
        sites = ports[port]
        print(f"port 0x{port:02x}: {len(sites)} uses")
        for s in sites[: args.show]:
            print("    " + s)
    print("note: ports addressed via DX (out dx, al) are not listed; "
          "look for `mov dx, imm` before them with `xref`.")


def cmd_xref(args):
    data = load(args.bin)
    for ins in disasm(data, org=args.org):
        for op in ins.operands:
            hit = (op.type == x86.X86_OP_IMM and op.imm & 0xFFFF == args.value) or \
                  (op.type == x86.X86_OP_MEM and op.mem.disp & 0xFFFF == args.value)
            if hit:
                print(f"0x{ins.address:06x}  {ins.mnemonic} {ins.op_str}")
                break


def cmd_calls(args):
    data = load(args.bin)
    for ins in disasm(data, org=args.org):
        if ins.mnemonic in ("call", "jmp") and len(ins.operands) == 1:
            op = ins.operands[0]
            if op.type == x86.X86_OP_IMM and op.imm & 0xFFFF == args.target:
                print(f"0x{ins.address:06x}  {ins.mnemonic} {ins.op_str}")


def int0(s):
    return int(s, 0)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("strings")
    s.add_argument("bin")
    s.add_argument("--min", type=int, default=5)
    s.set_defaults(fn=cmd_strings)
    s = sub.add_parser("dis")
    s.add_argument("bin")
    s.add_argument("start", type=int0)
    s.add_argument("len", type=int0)
    s.add_argument("--org", type=int0)
    s.set_defaults(fn=cmd_dis)
    s = sub.add_parser("io")
    s.add_argument("bin")
    s.add_argument("--show", type=int, default=8)
    s.set_defaults(fn=cmd_io)
    s = sub.add_parser("xref")
    s.add_argument("bin")
    s.add_argument("value", type=int0)
    s.add_argument("--org", type=int0)
    s.set_defaults(fn=cmd_xref)
    s = sub.add_parser("calls")
    s.add_argument("bin")
    s.add_argument("target", type=int0)
    s.add_argument("--org", type=int0)
    s.set_defaults(fn=cmd_calls)
    args = p.parse_args(argv)
    return args.fn(args) or 0


if __name__ == "__main__":
    sys.exit(main())
