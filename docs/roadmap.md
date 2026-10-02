# Roadmap

## M0: Tooling ✅
- `tools/akaidisk.py`: read and write S1000-format floppy images
  (`probe`, `ls`, `get`, `put`), with consistency checks after every write.
- `tools/patch.py`: apply verified patches and append NASM-assembled code.
- `tools/disasm.py`: strings (ASCII and Akai charset), disassembly, I/O-port
  map, cross-references, call-site search.
- `tools/vintage.py` + `src/dsp/`: vintage and auto-chop DSP, emulator-tested
  bit-exact against the Python model.
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

## M3: First hooks
- Hook the main loop (vector `PAYLOAD_OFF + 3`) and add an S1100FX page to
  the Utility menu showing the build date and selected mods.
- Find how the OS reads and writes sample RAM in chunks (the EDIT SAMPLE
  code). Both DSP cores are already streaming, so they plug straight in.

## M4: Feature mods
Most needed OS knowledge first:

| Mod | Built so far | Still needs from the OS |
|---|---|---|
| `vintage` | `crush.asm` + preset table, bit-exact with `vintage.py` | Sample RAM access, sample header (rate/length), EDIT SAMPLE menu slot |
| `autochop` | `chop.asm` transient detector, bit-exact with `vintage.py` | The above, plus creating samples/regions and a program with one keygroup per slice |
| `equal-chop` | Model (`vintage.py chop --equal`) | Same as `autochop` |
| `lazychop` | Nothing yet | Playback position; mark regions with MIDI keys or the front panel while the sample plays (like vubeatz Lazy chop) |
| `transpose` | Nothing yet | Program/keygroup tuning fields; a whole-program transpose and wider tuning range |
| `inputthru` | Nothing yet | ADC/DAC ports and sample-rate timer IRQ (vector `PAYLOAD_OFF + 6`): live input through the vintage presets |

**CPU budget (estimate).** In the emulator, `crush` runs about 16
instructions per sample and `chop` about 32 (two `IMUL`s). On a 10 MHz
V50 that is very roughly 200–500 cycles per sample, so processing a
stored sample takes about 1–2× its playing time. Fine for an edit-page
action. `inputthru` at 44.1 kHz would use nearly all the CPU, so it will
probably run at the preset's own lower rate, or need a hand-optimized
loop. Measure on hardware before committing to it.

## M5: Release
- Ship the way vubeatz does: the patcher plus mod specs. Users run it on
  their own stock OS disk and get `.img`/`.hfe` files out, so no Akai code
  is redistributed.
