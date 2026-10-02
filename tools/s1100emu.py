#!/usr/bin/env python3
"""Boot an S1100 OS file in an x86-16 emulator (no hardware model beyond
"the MIDI UART is always ready") and report what it does.

Useful for reverse engineering (which ports it touches, where it ends up
waiting) and as a smoke test for patched builds: a patched OS should
reach the same point as the stock one, with the payload copied into place.

    python3 tools/s1100emu.py build/stock_os.bin
    python3 tools/s1100emu.py build/s1100fx_os.bin --compare build/stock_os.bin

The ROM is not emulated: like the real boot ROM, we load the OS file at
physical 0 and start at 0000:0040 (see docs/os-map.md).
"""

import argparse
import collections
import sys

import unicorn
from unicorn import x86_const as R

ENTRY = 0x0040
# Port reads that must not return 0 for the boot to progress.
PORT_DEFAULTS = {
    0x8022: 0x05,  # V50 serial (MIDI) status: TX ready + TX empty
}


class Result:
    def __init__(self):
        self.ports = collections.Counter()
        self.pcs = collections.Counter()
        self.final = None
        self.error = None
        self.mem = None


def boot(os_data, max_insns=30_000_000):
    mu = unicorn.Uc(unicorn.UC_ARCH_X86, unicorn.UC_MODE_16)
    mu.mem_map(0, 0x100000)
    mu.mem_write(0, os_data)
    r = Result()

    def on_in(mu, port, size, _):
        r.ports[("in", port)] += 1
        return PORT_DEFAULTS.get(port, 0)

    def on_out(mu, port, size, value, _):
        r.ports[("out", port)] += 1

    def on_code(mu, addr, size, _):
        r.pcs[addr] += 1

    mu.hook_add(unicorn.UC_HOOK_INSN, on_in, None, 1, 0, R.UC_X86_INS_IN)
    mu.hook_add(unicorn.UC_HOOK_INSN, on_out, None, 1, 0, R.UC_X86_INS_OUT)
    mu.hook_add(unicorn.UC_HOOK_CODE, on_code)
    mu.reg_write(R.UC_X86_REG_CS, 0)
    try:
        mu.emu_start(ENTRY, 0xFFFFF, count=max_insns)
    except unicorn.UcError as exc:
        r.error = str(exc)
    r.final = (mu.reg_read(R.UC_X86_REG_CS), mu.reg_read(R.UC_X86_REG_IP))
    r.mem = bytes(mu.mem_read(0, 0x100000))
    return r


def summary(name, r):
    cs, ip = r.final
    print(f"{name}: stopped at {cs:04x}:{ip:04x}" + (f" ({r.error})" if r.error else ""))
    hot = r.pcs.most_common(1)[0]
    print(f"  hottest instruction: linear 0x{hot[0]:05x} ({hot[1]} times)")
    waits = [(p, n) for (d, p), n in r.ports.items() if d == "in" and n > 1000]
    for p, n in waits:
        print(f"  polling port 0x{p:04x} ({n} reads) -- needs a device model to go further")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("os")
    ap.add_argument("--compare", metavar="STOCK_OS", help="check a patched build against the stock OS")
    ap.add_argument("--insns", type=int, default=30_000_000)
    ap.add_argument("--ports", action="store_true", help="list every port touched")
    args = ap.parse_args(argv)
    with open(args.os, "rb") as f:
        data = f.read()
    r = boot(data, args.insns)
    summary(args.os, r)
    if args.ports:
        for (d, p), n in sorted(r.ports.items(), key=lambda kv: (kv[0][1], kv[0][0])):
            print(f"  {d:<3} 0x{p:04x}  {n}")
    if not args.compare:
        return 0

    with open(args.compare, "rb") as f:
        stock = f.read()
    s = boot(stock, args.insns)
    summary(args.compare, s)
    ok = True
    # Compare where each boot settles (its hottest loop), not the exact
    # stopping instruction, which depends on the instruction budget.
    if r.pcs.most_common(1)[0][0] != s.pcs.most_common(1)[0][0] or r.error != s.error:
        print("FAIL: patched OS settles somewhere else than stock")
        ok = False
    # The appended payload must have been copied to the 0x3000 segment.
    if len(data) > len(stock):
        tail_off = 0x15460
        want = data[len(stock):]
        lin = 0x30000 + (len(stock) - tail_off)
        got = r.mem[lin:lin + len(want)]
        if got == want:
            print(f"OK: payload ({len(want)} bytes) is in RAM at 3000:{lin - 0x30000:04x}")
        else:
            print("FAIL: payload not found in RAM at the expected address")
            ok = False
    print("OK: boots to the same point as stock" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
