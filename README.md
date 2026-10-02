# S1100FX

A mod pack for the Akai S1100, in the spirit of the
[vubeatz MPC2000 mods](https://vubeatz.com/mpc-mods.html) and
[S900FX](https://s900fx.com): new features patched into the **stock Akai
OS**, loaded from floppy (or a Gotek) at power-on. The ROMs are not
touched. Remove the disk and the machine is stock again.

Like the vubeatz mods, this repo doesn't ship Akai's OS. You run the
patcher on your own stock OS disk and choose which mods go in.

## Planned mods

| Mod | What it does | Status |
|---|---|---|
| `vintage` | Re-render a sample as an SP-1200, SP-12, MPC60, S900, S950, Mirage, 12-bit or 8-bit sampler: bit reduction plus sample-and-hold rate reduction, with no anti-alias filtering | DSP core done and emulator-tested. Needs OS hook |
| `autochop` | Find the hits in a sample, slice it into up to N regions (snapped to zero crossings) or N equal slices | DSP core done and emulator-tested. Needs OS hook |
| `banner` | S1100FX on the boot screen | Ready to try once you have a stock OS disk |
| Lazy chop, input thru, program transpose, more | See [roadmap](docs/roadmap.md) | Planned |

> **Status:** the build pipeline and the DSP cores work and are tested
> (V50 assembly run in an x86 emulator, bit-exact against a Python
> model). Nothing has run on a real S1100 yet. Hooking the mods into the
> OS needs a stock OS disk to reverse engineer. See
> [docs/roadmap.md](docs/roadmap.md).

## Hear the presets now

`tools/vintage.py` runs the same algorithms as the V50 code, on WAV files:

```sh
python3 tools/vintage.py presets
python3 tools/vintage.py crush break.wav break_sp1200.wav -p sp1200
python3 tools/vintage.py chop break.wav -n 16 -o slices/
```

Presets live in [presets/vintage.toml](presets/vintage.toml). After
editing it, run `make presets` to regenerate the assembler table.

## Layout

| Path | What |
|---|---|
| `tools/akaidisk.py` | Read/write Akai S1000-format floppy images |
| `tools/patch.py` | Apply a verified patch spec + append assembled code |
| `tools/disasm.py` | Reverse-engineering helpers (strings, I/O map, xrefs) |
| `tools/vintage.py` | Reference model for the DSP + WAV preview tool |
| `src/fx.asm` | New code (NASM, 80186 instruction set for the NEC V50) |
| `src/dsp/` | DSP cores: `crush.asm` (vintage), `chop.asm` (auto chop), presets |
| `patches/s1100fx.toml` | Base patch spec |
| `mods/*.toml` | One file per mod: OS hooks + build flags |
| `presets/vintage.toml` | Vintage sampler presets |
| `docs/` | Hardware notes, approach, roadmap |
| `original/` | *(git-ignored)* your stock OS disk image |
| `build/` | *(git-ignored)* outputs |

## Requirements

- Python 3.11+, `pip install -r requirements.txt` (capstone, unicorn)
- NASM 2.15+

## Build

```sh
cp /path/to/stock-s1100-os.img original/S1100_OS.img
python3 tools/akaidisk.py probe original/S1100_OS.img   # validate disk format
make ls                                                  # find the OS file name
make OS_NAME="S1100 OS" MODS="banner vintage autochop"  # -> build/S1100FX.img
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
