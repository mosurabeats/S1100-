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
- MAME test machine `s1100fx` + regression tests: `make emu`, `make test-emu`.

## M1: Prove the pipeline on hardware ← **next, needs your S1100**
The stock OS is extracted from Akai's `S11K-430.EXE` (`tools/sxd2img.py`),
and both test images boot like stock in the emulator.

1. `make first-test` → `build/S1100FX-first-test.img`. Text change only,
   same file size. On the MIDI page, `PROGRAMS IN MEMORY` should read
   `S1100FX  PROGRAMS`. This proves that our disk images and patches work
   on the machine.
2. `make` → `build/S1100FX.img`. Adds the 586-byte payload (nothing calls
   it yet), which pushes the OS file over 128 KB. It should behave exactly
   like stock. If (1) works and (2) doesn't, the boot ROM limits the OS
   file size, and new code will have to be loaded another way.

## M2: Map the OS (in progress, see os-map.md)
- ✅ Load address, boot stub, segment layout, V50 peripherals, MIDI UART.
- ✅ Emulated boot as far as the floppy controller (`tools/s1100emu.py`).
- ✅ Full emulated boot to the main page in MAME, with LCD text, keys and
  floppy access: the regression test environment (docs/emulator.md).
- ✅ Chip map (FDC, LCD, PPI, latch, voice chip, effects DSP) and the OS font.
- ☐ Text-drawing routine, main loop and key/wheel dispatch.
- ☐ Sample RAM access and data format (offset binary?).

## M3: First hooks
- Hook the main loop (far call to `PAYLOAD_SEG:PAYLOAD_ORG + 3`) and add an S1100FX page to
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
| `inputthru` | Nothing yet | ADC/DAC ports and sample-rate timer IRQ (`PAYLOAD_ORG + 6`): live input through the vintage presets |

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
