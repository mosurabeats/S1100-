# Roadmap

## M0: Tooling ✅
- `tools/akaidisk.py`: read and write S1000-format floppy images
  (`probe`, `ls`, `get`, `put`), with consistency checks after every write.
- `tools/patch.py`: apply verified patches and append NASM-assembled code.
- `tools/disasm.py`: strings (ASCII and Akai charset), disassembly, I/O-port
  map, cross-references, call-site search.
- Unit tests: `make test`.

## M1: Prove the pipeline (needs a stock OS disk)
1. Image a stock S1100 OS floppy to `original/S1100_OS.img` (1,638,400
   bytes). Use a Greaseweazle/KryoFlux, or copy a known-good image from a
   Gotek.
2. `python3 tools/akaidisk.py probe original/S1100_OS.img`. This checks
   the format assumptions against a real disk. If it reports problems, fix
   `akaidisk.py` before going further.
3. `make ls`, then `make OS_NAME="<name>"` with the OS file's name.
4. `python3 tools/disasm.py strings build/stock_os.bin | less`. Find the
   boot banner, put it in `patches/s1100fx.toml`, and enable the
   `boot-banner` patch.
5. Boot the S1100 from `build/S1100FX.img` and check the banner changed.
   **This is the first real-hardware milestone.**

## M2: Map the OS
- Also dump both EPROMs. The ROM's disk loader shows the RAM load
  address and entry point.
- Load `stock_os.bin` into Ghidra (language `x86:LE:16:Real Mode`) at the
  load address you found.
- Find the V50 relocation-register writes (see `hardware.md`), then label
  the ICU, timer and DMA ports.
- Find these routines (string cross-references help: `disasm.py xref`):
  LCD print, key/knob read, main loop, sampling (`Recording` and similar
  strings), playback IRQ.
- Record the findings in `docs/os-map.md` so patches can refer to them.

## M3: First hook
- Hook the main loop (vector `PAYLOAD_OFF + 3`) and add an S1100FX page to
  the Utility menu showing the build date, like S950FX does.

## M4: Real-time FX
- Find the ADC read and DAC write paths, then build a passthrough loop
  driven by the sample-rate timer IRQ (vector `PAYLOAD_OFF + 6`).
- Add bit-depth and sample-rate reduction, with controls on the FX page.

## M5: Release
- Ship `.img` and `.hfe` (HxC's `hxcfe` converts between them) with a
  README, like S950FX.
- Decide on distribution. Either publish full images (contains Akai code)
  or publish the patch spec and payload, and have users run `make` on their
  own stock disk.
