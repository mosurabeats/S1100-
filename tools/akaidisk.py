#!/usr/bin/env python3
"""Read and write Akai S1000/S1100-format floppy images (.img).

The S1000 family (S1000, S1100, S3000...) uses its own floppy filesystem,
not FAT12. Layout as implemented here (verified against the S1000 v4.40 and
S1100 v4.30 OS disks; run `probe` on any new image first):

  * 1024-byte blocks. DD disk = 800 blocks (819200 bytes),
    HD disk = 1600 blocks (1638400 bytes, 80 cyl x 2 heads x 10 x 1024).
  * Directory: 64 entries x 24 bytes at offset 0x000.
      name[12]   Akai character set (see AKAI_CHARS)
      pad[4]     0x20 on Akai-written disks
      type[1]    file type; 0 = unused slot (the name may be stale)
                 0x63 'c' OS, 0x70 'p' program, 0x73 's' sample,
                 0x78 'x' effects, 0x64 'd' drum inputs
      size[3]    little-endian byte count
      start[2]   little-endian first block
      osver[2]   little-endian OS version
  * FAT: one little-endian 16-bit word per block at offset 0x600.
      0x0000        free
      < nblocks     next block in chain
      >= 0x4000     marker (header/system block, end-of-chain)
    Akai disks use 0x4000 for header blocks and 0xC000 for end-of-chain;
    `put` still copies the codes it observes in the image it edits.
  * Volume label (12 bytes, Akai charset) right after the FAT.
"""

import argparse
import struct
import sys

BLOCK = 1024
DIR_ENTRIES = 64
DIR_ENTRY_SIZE = 24
FAT_OFFSET = 0x600
MARKER_MIN = 0x4000

GEOMETRIES = {
    819200: ("DD", 800),
    1638400: ("HD", 1600),
}

# 0-9, space, A-Z, # + - .
AKAI_CHARS = "0123456789 ABCDEFGHIJKLMNOPQRSTUVWXYZ#+-."


def akai_decode(raw):
    return "".join(AKAI_CHARS[b] if b < len(AKAI_CHARS) else "?" for b in raw)


def akai_encode(text, length=12):
    text = text.upper()
    out = bytearray()
    for ch in text[:length]:
        idx = AKAI_CHARS.find(ch)
        if idx < 0:
            raise ValueError(f"character {ch!r} not representable in Akai charset")
        out.append(idx)
    out.extend([AKAI_CHARS.index(" ")] * (length - len(out)))
    return bytes(out)


class DiskError(Exception):
    pass


class Entry:
    __slots__ = ("index", "name_raw", "unk", "type", "size", "start", "osver")

    @classmethod
    def parse(cls, index, raw):
        e = cls()
        e.index = index
        e.name_raw = raw[0:12]
        e.unk = raw[12:16]
        e.type = raw[16]
        e.size = raw[17] | raw[18] << 8 | raw[19] << 16
        e.start = struct.unpack_from("<H", raw, 20)[0]
        e.osver = struct.unpack_from("<H", raw, 22)[0]
        return e

    def pack(self):
        s = self.size
        return (self.name_raw + self.unk + bytes([self.type, s & 0xFF, (s >> 8) & 0xFF, (s >> 16) & 0xFF])
                + struct.pack("<HH", self.start, self.osver))

    @property
    def used(self):
        return self.type != 0

    @property
    def name(self):
        return akai_decode(self.name_raw).rstrip()


class AkaiFloppy:
    def __init__(self, data):
        if len(data) not in GEOMETRIES:
            raise DiskError(f"unexpected image size {len(data)}; expected one of {sorted(GEOMETRIES)}")
        self.data = bytearray(data)
        self.density, self.nblocks = GEOMETRIES[len(data)]
        self.label_offset = FAT_OFFSET + 2 * self.nblocks

    @classmethod
    def load(cls, path):
        with open(path, "rb") as f:
            return cls(f.read())

    def save(self, path):
        with open(path, "wb") as f:
            f.write(self.data)

    # --- raw structures -------------------------------------------------
    def entries(self):
        for i in range(DIR_ENTRIES):
            off = i * DIR_ENTRY_SIZE
            yield Entry.parse(i, self.data[off:off + DIR_ENTRY_SIZE])

    def write_entry(self, e):
        off = e.index * DIR_ENTRY_SIZE
        self.data[off:off + DIR_ENTRY_SIZE] = e.pack()

    def fat(self, block):
        return struct.unpack_from("<H", self.data, FAT_OFFSET + 2 * block)[0]

    def set_fat(self, block, value):
        struct.pack_into("<H", self.data, FAT_OFFSET + 2 * block, value)

    @property
    def label(self):
        return akai_decode(self.data[self.label_offset:self.label_offset + 12]).rstrip()

    # --- chains ---------------------------------------------------------
    def chain(self, start, size):
        """Return block list for a file, validating as we go."""
        need = max(1, -(-size // BLOCK))
        blocks, blk, seen = [], start, set()
        while True:
            if blk >= self.nblocks or blk in seen:
                raise DiskError(f"bad chain at block {blk} (from start {start})")
            seen.add(blk)
            blocks.append(blk)
            nxt = self.fat(blk)
            if nxt >= MARKER_MIN:
                break
            if nxt == 0:
                raise DiskError(f"chain from {start} hits free block after {blk}")
            blk = nxt
        if len(blocks) != need:
            raise DiskError(f"chain from {start} has {len(blocks)} blocks, size {size} needs {need}")
        return blocks

    def read_file(self, e):
        out = bytearray()
        for b in self.chain(e.start, e.size):
            out += self.data[b * BLOCK:(b + 1) * BLOCK]
        return bytes(out[:e.size])

    def find(self, name):
        """Find a used entry by name, or by slot as '#N' (the S1100 OS file
        has no printable name)."""
        if name.startswith("#"):
            e = list(self.entries())[int(name[1:])]
            return e if e.used else None
        for e in self.entries():
            if e.used and e.name == name.upper().rstrip():
                return e
        return None

    def observed_codes(self):
        """End-of-chain and system marker codes seen in this image."""
        eof, sysc = {}, {}
        for e in self.entries():
            if e.used:
                last = self.chain(e.start, e.size)[-1]
                code = self.fat(last)
                eof[code] = eof.get(code, 0) + 1
        file_blocks = set()
        for e in self.entries():
            if e.used:
                file_blocks.update(self.chain(e.start, e.size))
        for b in range(self.nblocks):
            v = self.fat(b)
            if v >= MARKER_MIN and b not in file_blocks:
                sysc[v] = sysc.get(v, 0) + 1
        return eof, sysc

    def delete(self, e):
        for b in self.chain(e.start, e.size):
            self.set_fat(b, 0)
        self.data[e.index * DIR_ENTRY_SIZE:(e.index + 1) * DIR_ENTRY_SIZE] = bytes(DIR_ENTRY_SIZE)

    def put(self, name, payload, ftype, osver=0, eof_code=None, template=None):
        """Store payload as a new file. `template` (an Entry) supplies
        unk/type/osver bytes when replacing an existing file."""
        if eof_code is None:
            eof, _ = self.observed_codes()
            if len(eof) != 1:
                raise DiskError(f"cannot infer end-of-chain code (seen {eof}); pass --eof-code")
            eof_code = next(iter(eof))
        free = [b for b in range(self.nblocks) if self.fat(b) == 0]
        need = max(1, -(-len(payload) // BLOCK))
        if need > len(free):
            raise DiskError(f"need {need} blocks, only {len(free)} free")
        slot = next((e for e in self.entries() if not e.used), None)
        if slot is None:
            raise DiskError("directory full")
        blocks = free[:need]
        for i, b in enumerate(blocks):
            chunk = payload[i * BLOCK:(i + 1) * BLOCK]
            self.data[b * BLOCK:(b + 1) * BLOCK] = chunk.ljust(BLOCK, b"\0")
            self.set_fat(b, blocks[i + 1] if i + 1 < need else eof_code)
        slot.name_raw = template.name_raw if template else akai_encode(name)
        slot.unk = template.unk if template else b"\x20" * 4
        slot.type = ftype
        slot.size = len(payload)
        slot.start = blocks[0]
        slot.osver = osver
        self.write_entry(slot)
        return slot

    def replace(self, name, payload, eof_code=None):
        """Replace an existing file, keeping its type, OS version and the
        end-of-chain code its old chain used."""
        old = self.find(name)
        if old is None:
            raise DiskError(f"no file named {name!r}")
        if eof_code is None:
            eof_code = self.fat(self.chain(old.start, old.size)[-1])
        self.delete(old)
        return self.put(old.name, payload, old.type, old.osver, eof_code, template=old)

    def defragment(self):
        """Rewrite all files contiguously in slot order, keeping their
        directory entries. The ROM OS loader may not follow fragmented
        chains, so images we produce never contain any."""
        eof, _ = self.observed_codes()
        if len(eof) > 1:
            raise DiskError(f"mixed end-of-chain codes {eof}")
        eof_code = next(iter(eof), 0xC000)
        files = [(e, self.read_file(e)) for e in self.entries() if e.used]
        header = [b for b in range(self.nblocks) if self.fat(b) >= MARKER_MIN
                  and not any(b in self.chain(e.start, e.size) for e, _ in files)]
        for b in range(self.nblocks):
            if b not in header:
                self.set_fat(b, 0)
        nxt = max(header) + 1 if header else 0
        for e, data in files:
            need = max(1, -(-len(data) // BLOCK))
            blocks = list(range(nxt, nxt + need))
            if blocks[-1] >= self.nblocks:
                raise DiskError("disk full while defragmenting")
            for i, b in enumerate(blocks):
                self.data[b * BLOCK:(b + 1) * BLOCK] = data[i * BLOCK:(i + 1) * BLOCK].ljust(BLOCK, b"\0")
                self.set_fat(b, blocks[i + 1] if i + 1 < need else eof_code)
            e.start = blocks[0]
            self.write_entry(e)
            nxt += need

    def contiguous(self, e):
        c = self.chain(e.start, e.size)
        return c == list(range(c[0], c[0] + len(c)))

    def check(self):
        """Self-consistency check; returns list of problems (empty = OK)."""
        problems, owner = [], {}
        for e in self.entries():
            if not e.used:
                continue
            try:
                for b in self.chain(e.start, e.size):
                    if b in owner:
                        problems.append(f"block {b} shared by {owner[b]!r} and {e.name!r}")
                    owner[b] = e.name
            except DiskError as exc:
                problems.append(f"{e.name!r}: {exc}")
        return problems


def cmd_probe(args):
    d = AkaiFloppy.load(args.image)
    print(f"{d.density} image, {d.nblocks} blocks, label {d.label!r}")
    problems = d.check()
    for p in problems:
        print("PROBLEM:", p)
    if not problems:
        eof, sysc = d.observed_codes()
        print("end-of-chain codes:", {hex(k): v for k, v in eof.items()})
        print("system/header codes:", {hex(k): v for k, v in sysc.items()})
        print("layout assumptions are consistent with this image")
    return 1 if problems else 0


def cmd_ls(args):
    d = AkaiFloppy.load(args.image)
    print(f"Volume {d.label!r} ({d.density})")
    for e in d.entries():
        if e.used:
            print(f"#{e.index:<2d} {e.name:<12}  type=0x{e.type:02x}  size={e.size:8d}  "
                  f"start={e.start:4d}  osver=0x{e.osver:04x}  unk={e.unk.hex()}")
    return 0


def cmd_get(args):
    d = AkaiFloppy.load(args.image)
    e = d.find(args.name)
    if not e:
        raise DiskError(f"no file named {args.name!r}")
    with open(args.out, "wb") as f:
        f.write(d.read_file(e))
    print(f"wrote {e.size} bytes to {args.out}")
    return 0


def cmd_put(args):
    d = AkaiFloppy.load(args.image)
    with open(args.file, "rb") as f:
        payload = f.read()
    if d.find(args.name):
        if not args.replace:
            raise DiskError(f"{args.name!r} exists; use --replace")
        e = d.replace(args.name, payload, args.eof_code)
        if not d.contiguous(e):
            d.defragment()
            e = d.find(f"#{e.index}")
    else:
        if args.type is None:
            raise DiskError("--type required for a new file")
        e = d.put(args.name, payload, args.type, args.osver or 0, args.eof_code)
    problems = d.check()
    if problems:
        raise DiskError("image failed check after write: " + "; ".join(problems))
    d.save(args.out or args.image)
    print(f"stored {e.name!r}: {e.size} bytes from block {e.start}")
    return 0


def int0(s):
    return int(s, 0)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("probe", help="validate layout assumptions against an image")
    s.add_argument("image")
    s.set_defaults(fn=cmd_probe)
    s = sub.add_parser("ls", help="list files")
    s.add_argument("image")
    s.set_defaults(fn=cmd_ls)
    s = sub.add_parser("get", help="extract a file")
    s.add_argument("image")
    s.add_argument("name")
    s.add_argument("out")
    s.set_defaults(fn=cmd_get)
    s = sub.add_parser("put", help="store a file")
    s.add_argument("image")
    s.add_argument("name")
    s.add_argument("file")
    s.add_argument("-o", "--out", help="write result here instead of modifying IMAGE")
    s.add_argument("--replace", action="store_true")
    s.add_argument("--type", type=int0)
    s.add_argument("--osver", type=int0)
    s.add_argument("--eof-code", type=int0)
    s.set_defaults(fn=cmd_put)
    args = p.parse_args(argv)
    try:
        return args.fn(args)
    except DiskError as exc:
        print("error:", exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
