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
| `banner` | S1100FX in the `PROGRAMS IN MEMORY` page title | **Ready for a hardware test** |
| Lazy chop, input thru, program transpose, more | See [roadmap](docs/roadmap.md) | Planned |

> **Status:** the build runs on Akai's S1100 OS v4.30. The OS memory map
> is worked out ([docs/os-map.md](docs/os-map.md)), and patched builds boot
> like stock in an emulator. The DSP cores are bit-exact against a Python
> model. **Nothing has run on a real S1100 yet:** the two test images in
> [roadmap M1](docs/roadmap.md) are the next step. The mods are not yet
> hooked into the OS menus.

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
| `tools/sxd2img.py` | Extract the floppy image from Akai's DOS OS-update EXE |
| `tools/akaidisk.py` | Read/write Akai S1000-format floppy images |
| `tools/s1100emu.py` | Boot an OS file in an emulator; compare patched vs stock |
| `tools/patch.py` | Apply a verified patch spec + append assembled code |
| `tools/disasm.py` | Reverse-engineering helpers (strings, I/O map, xrefs) |
| `tools/vintage.py` | Reference model for the DSP + WAV preview tool |
| `src/fx.asm` | New code (NASM, 80186 instruction set for the NEC V50) |
| `src/dsp/` | DSP cores: `crush.asm` (vintage), `chop.asm` (auto chop), presets |
| `patches/s1100fx.toml` | Base patch spec |
| `mods/*.toml` | One file per mod: OS hooks + build flags |
| `presets/vintage.toml` | Vintage sampler presets |
| `docs/` | Hardware notes, OS memory map, approach, roadmap |
| `original/` | *(git-ignored)* Akai's `S11K-430.EXE` or your stock OS image |
| `build/` | *(git-ignored)* outputs |

## Requirements

- Python 3.11+, `pip install -r requirements.txt` (capstone, unicorn)
- NASM 2.15+

## Build

Get Akai's S1100 OS v4.30 update (`S11K-430.EXE`) and put it in
`original/`. The build extracts the disk from it by running Akai's DOS
program in an emulator, so you don't need a PC with a floppy drive.

```sh
make first-test      # -> build/S1100FX-first-test.img  (text change only)
make                 # -> build/S1100FX.img  (MODS="banner vintage autochop")
make test
python3 tools/s1100emu.py build/s1100fx_os.bin --compare build/stock_os.bin
```

Write an image to an HD floppy as raw sectors, or copy it to a Gotek
running FlashFloppy with `host = akai`. Boot the S1100 with it inserted.
Remove the disk and power-cycle to return to stock.

## Docs

- [OS map](docs/os-map.md): boot sequence, segments, I/O ports
- [Approach](docs/approach.md): how S900FX/S950FX work and how this
  project copies them
- [Hardware](docs/hardware.md): CPU, memory, what still needs verifying
- [Roadmap](docs/roadmap.md): milestones

No Akai code is included in this repository.
