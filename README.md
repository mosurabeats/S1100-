# S1100FX

A custom operating system for the Akai S1100, in the spirit of
[S900FX](https://s900fx.com) / [S950FX](https://s950fx.com).

Like those projects, S1100FX is the **stock Akai OS, patched and extended
with new code**, loaded from floppy (or a Gotek) at power-on. The ROMs are
not touched. Remove the disk and the machine is stock again.

> **Status:** M0, tooling. The build pipeline works and is tested, but no
> S1100-specific patches exist yet. They need a stock OS disk to reverse
> engineer. See [docs/roadmap.md](docs/roadmap.md).

## Layout

| Path | What |
|---|---|
| `tools/akaidisk.py` | Read/write Akai S1000-format floppy images |
| `tools/patch.py` | Apply a verified patch spec + append assembled code |
| `tools/disasm.py` | Reverse-engineering helpers (strings, I/O map, xrefs) |
| `src/fx.asm` | New code (NASM, 80186 instruction set for the NEC V50) |
| `patches/s1100fx.toml` | Patches to the stock OS |
| `docs/` | Hardware notes, approach, roadmap |
| `original/` | *(git-ignored)* your stock OS disk image |
| `build/` | *(git-ignored)* outputs |

## Requirements

- Python 3.11+, `pip install -r requirements.txt` (capstone)
- NASM 2.15+

## Build

```sh
cp /path/to/stock-s1100-os.img original/S1100_OS.img
python3 tools/akaidisk.py probe original/S1100_OS.img   # validate disk format
make ls                                                  # find the OS file name
make OS_NAME="S1100 OS"                                  # -> build/S1100FX.img
make test
```

Write `build/S1100FX.img` to an HD floppy as raw sectors, or copy it to a
Gotek running FlashFloppy with `host = akai`.

## Docs

- [Approach](docs/approach.md): how S900FX/S950FX work and how this
  project copies them
- [Hardware](docs/hardware.md): CPU, memory, what still needs verifying
- [Roadmap](docs/roadmap.md): milestones

No Akai code is included in this repository.
