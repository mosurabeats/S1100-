#!/usr/bin/env python3
"""Apply a patch spec (TOML) to a stock Akai OS binary.

Every patch is verified before it is applied: either the original bytes at
`offset` must equal `expect`, or `find` must match exactly once. A patch
spec that does not match the input binary fails loudly instead of producing
a corrupt OS.

Spec format (see patches/s1100fx.toml):

  [base]
  sha256 = "..."          # optional: refuse any other input binary

  [payload]               # optional: new code appended to the OS
  source = "src/fx.asm"   # assembled with NASM (cpu 186 enforced in source)
  align = 16              # pad OS to this alignment before appending

  [[patch]]
  name = "boot-banner"
  find_text = "S1100"     # or find = "hex bytes", or offset + expect
  replace_text = "S1KFX"  # or replace = "hex bytes", or asm = "..."

`asm` patches are assembled with `bits 16`, `cpu 186` and `org` set to the
patch's `org` key (default: the file offset). These NASM macros are defined
for both the payload and asm patches:
  PAYLOAD_OFF   file offset where the payload starts
  OS_SIZE       size of the unpatched OS
"""

import argparse
import hashlib
import os
import re
import subprocess
import sys
import tempfile
import tomllib

FORBIDDEN_PREFIXES = (0x66, 0x67)  # 386 operand/address-size: illegal on the V50


class PatchError(Exception):
    pass


def parse_hex(s):
    return bytes.fromhex(re.sub(r"[\s,]", "", s))


def nasm(source, defines, include_dir=None):
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "in.asm")
        out = os.path.join(tmp, "out.bin")
        with open(src, "w") as f:
            f.write(source)
        cmd = ["nasm", "-f", "bin", "-o", out, src]
        if include_dir:
            cmd += ["-I", include_dir.rstrip("/") + "/"]
        for k, v in defines.items():
            cmd.append(f"-D{k}={v}")
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode:
            raise PatchError("nasm failed:\n" + r.stderr)
        with open(out, "rb") as f:
            return f.read()


def locate(data, patch):
    name = patch.get("name", "?")
    if "find" in patch or "find_text" in patch:
        needle = parse_hex(patch["find"]) if "find" in patch else patch["find_text"].encode("latin-1")
        hits = [m.start() for m in re.finditer(re.escape(needle), data)]
        if len(hits) != 1:
            msg = f"patch {name!r}: pattern found {len(hits)} times (need exactly 1)"
            if hits:
                msg += ": " + ", ".join(hex(h) for h in hits[:10])
            elif "find_text" in patch:
                msg += suggest(data, patch["find_text"])
            raise PatchError(msg)
        return hits[0], needle
    if "offset" not in patch:
        raise PatchError(f"patch {name!r}: needs find, find_text or offset")
    off = patch["offset"]
    expect = parse_hex(patch["expect"]) if "expect" in patch else None
    if expect is None:
        raise PatchError(f"patch {name!r}: offset patches must give `expect` bytes")
    actual = data[off:off + len(expect)]
    if actual != expect:
        raise PatchError(f"patch {name!r}: at 0x{off:x} expected {expect.hex(' ')}, found {actual.hex(' ')}")
    return off, expect


def suggest(data, text):
    """Show printable strings sharing a word with `text` to help fix specs."""
    words = [w for w in re.split(r"\W+", text) if len(w) >= 3]
    found = []
    for m in re.finditer(rb"[\x20-\x7e]{4,}", data):
        s = m.group().decode("latin-1")
        if any(w.lower() in s.lower() for w in words):
            found.append(f"  0x{m.start():x}: {s!r}")
    return ("\nsimilar strings in binary:\n" + "\n".join(found[:20])) if found else ""


def build(spec, os_data, spec_dir):
    base = spec.get("base", {})
    want = base.get("sha256")
    if want:
        got = hashlib.sha256(os_data).hexdigest()
        if got != want.lower():
            raise PatchError(f"input sha256 {got} does not match spec {want}")

    out = bytearray(os_data)
    payload_cfg = spec.get("payload")
    align = payload_cfg.get("align", 16) if payload_cfg else 16
    payload_off = -(-len(out) // align) * align
    defines = {"PAYLOAD_OFF": payload_off, "OS_SIZE": len(os_data)}

    # Locate everything against the *original* bytes first so patches
    # cannot accidentally match each other's output.
    planned = []
    for patch in spec.get("patch", []):
        if not patch.get("enabled", True):
            continue
        off, orig = locate(os_data, patch)
        if "replace" in patch:
            new = parse_hex(patch["replace"])
        elif "replace_text" in patch:
            new = patch["replace_text"].encode("latin-1")
            if len(new) != len(orig):
                raise PatchError(f"patch {patch['name']!r}: replace_text must be {len(orig)} bytes, got {len(new)}")
        elif "asm" in patch:
            org = patch.get("org", off)
            new = nasm(f"bits 16\ncpu 186\norg {org}\n{patch['asm']}\n", defines, spec_dir)
            lint_186(new, patch.get("name", "?"))
        else:
            raise PatchError(f"patch {patch.get('name')!r}: no replacement given")
        if "max_len" in patch and len(new) > patch["max_len"]:
            raise PatchError(f"patch {patch['name']!r}: {len(new)} bytes exceeds max_len {patch['max_len']}")
        planned.append((patch.get("name", "?"), off, new))

    planned.sort(key=lambda p: p[1])
    for (n1, o1, b1), (n2, o2, _) in zip(planned, planned[1:]):
        if o1 + len(b1) > o2:
            raise PatchError(f"patches {n1!r} and {n2!r} overlap")
    for name, off, new in planned:
        if off + len(new) > len(out):
            raise PatchError(f"patch {name!r} runs past end of OS")
        out[off:off + len(new)] = new
        print(f"  patched {name:<24} 0x{off:06x}  {len(new)} bytes")

    if payload_cfg:
        src_path = os.path.join(spec_dir, payload_cfg["source"])
        with open(src_path) as f:
            code = nasm(f.read(), defines, os.path.dirname(src_path))
        out.extend(b"\0" * (payload_off - len(out)))
        out.extend(code)
        print(f"  payload {payload_cfg['source']} at 0x{payload_off:06x}  {len(code)} bytes")

    return bytes(out), planned


def lint_186(blob, label):
    """Best-effort guard against 386-only encodings sneaking in."""
    try:
        import capstone
    except ImportError:
        return
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_16)
    for ins in md.disasm(blob, 0):
        if ins.bytes[0] in FORBIDDEN_PREFIXES:
            raise PatchError(f"{label}: 386-only prefix at +0x{ins.address:x}: {ins.mnemonic} {ins.op_str}")


def main(argv=None):
    p = argparse.ArgumentParser(description="Apply a patch spec to an Akai OS binary")
    p.add_argument("spec")
    p.add_argument("input", help="stock OS binary (extracted with akaidisk.py get)")
    p.add_argument("output")
    args = p.parse_args(argv)
    with open(args.spec, "rb") as f:
        spec = tomllib.load(f)
    with open(args.input, "rb") as f:
        os_data = f.read()
    try:
        out, _ = build(spec, os_data, os.path.dirname(os.path.abspath(args.spec)))
    except PatchError as exc:
        print("error:", exc, file=sys.stderr)
        return 2
    with open(args.output, "wb") as f:
        f.write(out)
    print(f"wrote {len(out)} bytes to {args.output} (was {len(os_data)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
