# Akai S1100 hardware: what we know

Each fact is tagged with how sure we are. **Verify** items need checking
against the S1100 service manual or a real machine before code depends on
them.

| Item | Value | Confidence |
|---|---|---|
| CPU | NEC µPD70216GF-10 (**V50**), 10 MHz | Reported in hardware listings. **Verify** on the board |
| Instruction set | 8086/80186 (+ V-series extras we don't use) | Follows from V50 |
| CPU address space | 1 MB, real-mode segment:offset | Follows from V50 |
| Firmware | Two EPROMs on the main board (even/odd bytes of a 16-bit bus) | High: these are routinely swapped for upgrades |
| OS from disk | On boot, the ROM OS looks for an OS file on floppy/SCSI and loads it in place of itself | High: it's how Akai shipped updates |
| OS versions | 4.x (4.3 added S3000 compatibility, 2-track HD recording) | High |
| Sample RAM | 2 MB stock, 32 MB max (EXM008 boards) | High |
| Sample RAM access | Must sit behind custom gate arrays, because 2–32 MB exceeds the V50's 1 MB space | Inferred. **Verify** |
| Audio | 16-bit converters, 24-bit internal processing, digital filters, effects send/return | High |
| Floppy | Akai S1000 format, HD 1.6 MB (80×2×10×1024 B); DD 800 KB also readable | High |
| Floppy emulator | FlashFloppy (Gotek) supports it with `host = akai` in FF.CFG | High |

## V50 specifics that matter for reverse engineering

The V50 has built-in peripherals (interrupt controller similar to the 8259,
timer/counter similar to the 8254, DMA controller similar to the 8237, and a
serial port). Their I/O base addresses are set at boot by writing relocation
registers near the top of I/O space (around `0xFFF0`–`0xFFFF`: OPCN,
OPSEL, OPHA, DULA, IULA, TULA, SULA, WCY*). Check the exact registers in
the µPD70216 datasheet.

**Why this matters:** the stock OS's init code writes those registers, so
the first few hundred instructions show where the ICU, timers and DMA
appear in I/O space. With that known, `tools/disasm.py io` output becomes
readable:

- timer ports → the sample-rate clock and UI tick
- DMA ports → how audio moves between the converters and sample RAM
- ICU ports → which IRQ is the audio/sample interrupt (our hook point for
  real-time processing)
- everything else → custom gate arrays, LCD, front-panel, FDC, SCSI

## Unknowns to resolve (milestone 2)

1. Where the ROM loads the disk OS in RAM, and its entry point.
2. Whether the OS file has a header before the code.
3. Which I/O ports are the ADC and DAC (or the gate-array registers in
   front of them), and how they're clocked.
4. LCD write routine (40×8 character LCD) and front-panel/knob input.
5. Free RAM we can use for new code and state.

## Sources

- [Akai S1100 service manual (manualslib)](https://www.manualslib.com/manual/1266079/Akai-S1100.html)
- [Akai S1000HD service manual (manualslib)](https://www.manualslib.com/manual/1002134/Akai-S1000hd.html)
- [Circuitbenders: Akai OS update EPROMs](https://www.circuitbenders.co.uk/forsale/akaiOS/akaiOS.html)
- [Akai S1000 (Wikipedia)](https://en.wikipedia.org/wiki/Akai_S1000)
- [S1000/S1100 32 MB memory (firstpr.com.au)](https://www.firstpr.com.au/rwi/smem/)
- [FlashFloppy issue: Akai S1100](https://github.com/keirf/FlashFloppy/issues/325)
