# Test environment: MAME

S1100FX uses two emulators, for different jobs:

| | `tools/s1100emu.py` (Unicorn) | `s1100fx` (MAME) |
|---|---|---|
| What it models | The V50 CPU only, plus a few port stubs | The whole S1100 as emulated by MAME: V50 with its peripherals, µPD72069 floppy controller, LC7981 LCD, 8255 front panel and data wheels, SCSI, MIDI |
| Good for | Fast boot smoke tests, tracing ports | Seeing the LCD, pressing keys, loading disks: **regression tests** |
| Needs | `pip install unicorn` | A one-time MAME build (`emu/mame/build.sh`) |

## The `s1100fx` machine

MAME (0.289) already has an Akai S1100 driver, `src/mame/akai/s1000.cpp`,
written by Devin Acker. It needs the S1100's boot ROM dumps, which we
don't have. `emu/mame/s1100fx.ipp` adds a variant machine, `s1100fx`, that
boots **without** them:

- `-quickload FILE` loads an OS into RAM at physical 0 and starts it at
  `0000:0040`, which is what the real boot ROM does (`docs/os-map.md`).
  `FILE` can be a raw OS file (`build/s1100fx_os.bin`) or an Akai floppy
  image, in which case the first OS file (type `0x63`) on the disk is used.
- The same floppy image goes into the emulated drive (`-flop`), so the OS
  can read the rest of the disk through the real floppy controller.
- The L6009 voice-chip ROMs are left empty: there's no sound, which
  doesn't matter for UI and logic tests.

What it can't tell you: anything the real boot ROM does differently
(including whether it accepts OS files over 128 KB), timing-exact behavior,
and audio. The effects DSP (DSP56001) isn't emulated in MAME either.

If you dump your S1100's two boot ROMs (`akai_s1100_osv4_30_lsb/msb`), the
stock `s1100` driver in the same binary runs the real boot path.

## Build

```sh
emu/mame/build.sh          # clones MAME 0.289 into build/mame, builds emu/bin/s1100fx
```

The script copies `s1100fx.ipp` into MAME's tree, adds two lines to
`s1000.cpp` (an include and the machine's registration), and builds
**only** that driver (`SUBTARGET=s1100fx SOURCES=src/mame/akai/s1000.cpp`).
The first build takes around 30–60 minutes on 4 cores; later ones are
incremental. Requirements: a C++17 compiler, Python 3, and the SDL2 and
fontconfig development packages (`libsdl2-dev libsdl2-ttf-dev
libfontconfig1-dev` on Debian/Ubuntu).

## Run it yourself

```sh
emu/bin/s1100fx s1100fx -quickload build/S1100FX.img -flop build/S1100FX.img
```

Keys follow the driver's mapping: `Q W E R T Y U I` are the mode buttons
(Select Prog, Edit Sample, Edit Prog, MIDI, Disk, Master Tune, Drum,
Option), `1`–`8` are F1–F8, the keypad is the number pad, and the arrow
keys are the cursor and data wheels.

## Automated tests

`tools/s1100test.py` runs the machine headlessly (`-video none -sound
none -nothrottle`) with `emu/lua/harness.lua`. The harness runs a step file
(wait, press a key, snapshot the LCD, dump memory, exit) and writes each
LCD snapshot as a 240×64 text bitmap.

```sh
python3 tools/s1100test.py boot build/S1100FX.img                  # LCD after boot
python3 tools/s1100test.py boot build/S1100FX.img --press KEY3:MIDI
```

`tests/test_mame.py` uses this for regression tests. They run whenever
`emu/bin/s1100fx` and `original/S11K-430.EXE` both exist, and are skipped
otherwise.
