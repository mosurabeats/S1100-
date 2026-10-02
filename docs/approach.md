# Approach: how S900FX/S950FX work, and how S1100FX copies them

## What the S950FX release contains

We inspected the S950FX 2026.09.21 release from
[SourceForge](https://sourceforge.net/projects/s950fx/files/) (s900fx.com
itself wasn't reachable from the build environment, but S900FX is by the
same author and works the same way):

- An 819,200-byte (800 KB DD) Akai **S900-format** floppy image, plus HFE
  copies for emulators that need them.
- One directory entry, `S950FX`.
- The file holds **Akai's original OS**: the stock strings are still there
  (`AKAI S950 1.2`, `MS950  1.5`, the menu pages, `OOPS! Disk not mounted.`
  and so on).
- **New strings appended after the stock code** (from about offset
  `0xC455`): `S950FX`, `s950fx.com | mikefeedback.com`, the build date,
  `S950FX Rate:`, `S950FX Filter:`, ` Anti-Alias:`, `K REC:` / ` PLAY:`.

So S950FX is **the stock OS, patched, with new code and data added to the
end**, delivered the same way Akai delivered OS updates: put the disk in
the drive and switch on. No ROM swap, nothing permanent. Remove the disk
and the stock OS is back.

## S1100FX uses the same model

```
stock OS floppy ──akaidisk get──▶ stock_os.bin
                                     │
         patches/s1100fx.toml ──────▶│ patch.py: verified byte patches
         src/fx.asm (NASM, cpu 186) ▶│           + payload appended
                                     ▼
                               s1100fx_os.bin ──akaidisk put──▶ S1100FX.img
```

- **Patches are verified.** Each one states the original bytes it expects
  (or a unique pattern). If you run the spec against a different OS
  version, it fails instead of writing a broken OS.
- **New code goes in `src/fx.asm`.** It's locked to the 80186 instruction
  set, so 386-only instructions fail at build time instead of crashing the
  V50.
- **Hooks are small `asm` patches.** Each one swaps a CALL in the stock OS
  for a call into the payload's vector table. The payload then does its
  work and calls the original routine.
- **No Akai code is committed.** `original/` and `build/` are git-ignored.
  The repo is effectively a patch: anyone with a stock S1100 OS disk can
  rebuild the image themselves.

## What "FX" could mean on an S1100

S900FX passes live input through the 12-bit converters to add their
character. The S1100 is already a clean 16-bit sampler, so the useful
equivalents are things it can't do now:

- **Live passthrough with degradation**: input → ADC → bit-depth and
  sample-rate reduction → DAC, with 12-bit, 8-bit and SP-1200-style modes.
- Real-time use of the S1100's existing digital filters and effects
  send/return on the live input.
- Small quality-of-life patches: a faster boot, default settings, extra
  MIDI CC mappings.

Which of these comes first is a product decision. See `roadmap.md`.
