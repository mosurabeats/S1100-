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

## Other I/O seen during boot (meaning mostly **open**)

| Ports | Seen | Guess |
|---|---|---|
| `0x2000` | read in INT `0x0E`/`0x0F` handlers (`0000:00BB`, `0000:00D6`): bit `0x20`/`0x80` decides ±1 on counters at `0000:00F7–00FA` | front-panel data wheel / encoders |
| `0x2002`–`0x2006` | init writes; `0x2004 ← 0xAA` in the INT 0 handler | panel/LED/watchdog |
| `0x4000–0x40BE`, `0x5060–0x51FE` | one write each at init | voice/DSP chip registers (16 voices × several params) |
| `0x40E0`, `0x40E8`, `0x40F0` | the most-used ports in the code | voice/DSP control |
| `0x6000`/`0x6004` | index/data pairs, regs `0,1,2,3,4,8–0xC`; polls `0x6006` | SCSI controller (layout looks like an MB89352) |
| `0x7780–0x77E0`, `0x7800–0x781E` | boot waits forever on `0x7814` | floppy controller (next device to model) |
| `0x3000`–`0x301E` | init | **open** |

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

1. Model the device at `0x7814` well enough to get past it, so the emulated
   boot reaches the main loop and its first LCD writes.
2. Find the LCD output path. Following the code that references
   `PROGRAMS IN MEMORY` (3000:1362) is the shortcut.
3. Find the main loop and its key/wheel dispatch, then add the first
   `fx_tick` hook.
4. Find how sample RAM is read and written (EDIT SAMPLE functions).
