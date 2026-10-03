# S1100 OS v4.30: memory map and findings

Source: Akai's `S11K-430.EXE` update, extracted with `tools/sxd2img.py`.
The OS file is slot `#0` on the disk: type `0x63`, 130,784 bytes, disk
osver `0x091E`, sha256 `6a32cce7…3272`. Its name field is twelve `0x20`
bytes, so refer to it by slot. The S1000 v4.40 disk (`S1K-440.EXE`) has
the same layout: its OS file is 102,208 bytes, osver `0x0428`.

Everything below was checked by disassembly, by booting the OS in
`tools/s1100emu.py`, or both. Items still open are marked **open**.

## Boot

1. The boot ROM (not available to us) loads the OS file at physical
   address 0 and jumps to `0000:0040`. **Open:** whether the ROM limits the
   file size; the stock file is just under 128 KB.
2. Bytes `0x00–0x3F` of the file are the first 16 interrupt vectors.
3. The stub at `0000:0040` reads two paragraph values from the file,
   `[0xF3] = 0x0548` and `[0xF5] = 0x1546`, then:
   - copies file `0x15460…end` to `3000:0000`. The length is
     `0x1FEE - 0x1546` paragraphs, and `0x1FEE` is the file size: this is
     the `mov ax,0x1FEE` at file offset `0x75` that the base spec patches;
   - copies file `0x05480–0x1545F` to `1000:0000`, backwards because the
     ranges overlap;
   - jumps to `1000:0000`, the main entry.

| Runtime | File range | Size | Contents |
|---|---|---|---|
| `0000:0000` | `0x00000–0x0547F` | 21 KB | vectors, small ISRs, UI strings, variables |
| `1000:0000` | `0x05480–0x1545F` | 64 KB | main code |
| `3000:0000` | `0x15460–0x1FEDF` | 43 KB | more code/strings (169 far calls 1000→3000, 119 back) |
| `3000:AA80` | appended | — | **S1100FX payload** (below 64 KB: ~21 KB available) |
| `2000`, `4000`–`9000` | — | — | RAM used at runtime (written during boot) |

File offset → runtime: `seg 0x1000: off - 0x5480`, `seg 0x3000: off - 0x15460`.

## V50 internal peripherals

The OS programs the V50 relocation registers at `0xFFF0–0xFFFE` early in
boot. OPHA = `0x80`, so the internal peripherals sit at `0x80xx`:

| Peripheral | Ports | Notes |
|---|---|---|
| DMA (DULA `0x00`) | `0x8000–0x800F` | |
| Interrupt controller (IULA `0x10`) | `0x8010–0x8013` | vector base 8: IRQ n → INT 8+n |
| Serial (SULA `0x20`) | `0x8020` data, `0x8022` status/cmd | **MIDI**. Bit 0 of status = TX ready. TX routine `1000:13A2`, RX ISR = INT 9 `1000:13B1` |
| Timer (TULA `0x30`) | `0x8030–0x8036` | control writes `0x24`, `0x56`, `0xA4` |

## Other I/O

Identified with MAME's S1100 driver (`src/mame/akai/s1000.cpp`, by Devin
Acker), and confirmed by booting the OS in it (docs/emulator.md):

| Ports | Chip | Notes |
|---|---|---|
| `0x0000–0x001F` | MB89352 SCSI controller | |
| `0x1000`/`0x1002` | µPD72069 floppy controller (µPD765 family) | status `0x1000` (RQM/DIO bits), data `0x1002` |
| `0x2000–0x2006` | 8255 PPI | port A = key matrix and data/cursor wheels, B = key row select, C = LEDs; `0x2006 ← 0x90` |
| `0x3000–0x3FFF` | 74HC259 latch / footswitch input | ADC clock, mute, floppy select/motor/density, FDC reset |
| `0x4000–0x5FFF` | Akai L6009 voice chip | sample playback registers |
| `0x6000–0x6006` | LC7981 (HD61830-compatible) LCD controller | data `0x6000`, command `0x6004`, status `0x6006`. 240×64 graphics mode |
| `0x7800–0x781E` | DSP56001 host interface (effects) | microcode loaded as 512 × 24-bit words through `0x780A/C/E`; status `0x7814` (bit 1 ready, bit 4 busy) |
| `INTP5`/`INTP6` | cursor/data wheels | gray code; handlers `0000:00BB`, `0000:00D6` |

## LCD text

The OS draws text itself in graphics mode, with a 5×7 font in 6-pixel
cells: 97 glyphs, 8 bytes each, ASCII order from `0x20`, at file offset
`0x19CF0` (3000:4890). The leftmost pixel is bit 0. `tools/s1100test.py`
uses this font (read from the OS under test) to turn LCD snapshots back
into text.

## Strings

- Plain ASCII, for example `PROGRAMS IN MEMORY` at file `0x167C2` (3000:1362),
  `S1100 SCSI ID:`, `no function in S1100EX`.
- There is no "AKAI" or version text, so the power-on banner is in the ROM.
- `0123456789 ABCDEFGHIJKLMNOPQRSTUVWXYZ#+-.` at `0x500` is the Akai
  character set table used for names.

## Sample data

Akai's S1000 SysEx document says sample words are 16-bit **straight
binary** (`0x0000`–`0xFFFF`, i.e. offset binary). **Open:** whether sample
RAM uses the same format. If it does, the DSP cores (signed int16) need
`xor 0x8000` on the way in and out.

## Next targets

1. ✅ Boot to the main page in an emulator: done in MAME (docs/emulator.md).
2. Find the OS's text-drawing routine. It reads the font at 3000:4890,
   and following the code that references `PROGRAMS IN MEMORY` (3000:1362)
   is another shortcut. MAME's debugger (`-debug`) can break on reads of
   the font.
3. Find the main loop and its key/wheel dispatch, then add the first
   `fx_tick` hook.
4. Find how sample RAM is read and written (EDIT SAMPLE functions).
