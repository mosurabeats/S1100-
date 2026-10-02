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

## Feature direction: a mod pack

The target is closer to the vubeatz MPC2000/2000XL mods than to a single
effect: a set of independent features (vintage sampler presets, auto chop,
lazy chop, transpose, input thru) that you choose at build time. Each mod
is one file in `mods/` (its OS hooks plus a `MOD_<NAME>` build flag), and
`src/fx.asm` compiles in only the selected ones.

DSP code is written once as a Python reference model (`tools/vintage.py`)
and once in V50 assembly (`src/dsp/`). The tests run the assembly in an
x86-16 emulator and require the output to be **bit-exact** with the
model. So the algorithm can be tuned on a computer with WAV files, and the
on-hardware version is known to sound identical.

Both DSP cores are **streaming**: they process any chunk size and keep
their state between calls. That is required because the V50 can only
address 1 MB, while S1100 sample RAM is 2–32 MB behind custom hardware, so
the OS will have to feed samples through in pieces.
