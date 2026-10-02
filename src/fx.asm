; S1100FX payload -- new code appended to the end of the stock S1100 OS.
;
; Target CPU: NEC uPD70216 (V50). It runs the 80186 instruction set, so
; NASM is locked to `cpu 186`: any 386 instruction or register is a
; build error rather than a crash on the hardware.
;
; patch.py defines:
;   PAYLOAD_OFF  file offset of this payload inside the OS image
;   OS_SIZE      size of the stock OS
;
; How control gets here: an `asm` patch in patches/s1100fx.toml replaces
; an instruction in the stock OS (e.g. the main UI loop or a timer ISR)
; with a CALL to one of the entry points below. The vector table lives at
; a fixed position so patches can target PAYLOAD_OFF + n without knowing
; the payload's internal layout.
;
; Runtime addresses: `org` must equal the offset this code will have in
; its code segment once the OS is loaded into RAM. Until the load address
; and segment layout are reverse-engineered (docs/roadmap.md, milestone 2)
; we assume CS:0 == file offset 0, i.e. the payload runs at PAYLOAD_OFF.

bits 16
cpu 186
org PAYLOAD_OFF

; --- entry vector table (fixed layout: 3 bytes per entry) --------------
vectors:
    jmp near fx_init        ; PAYLOAD_OFF + 0 : called once at boot
    jmp near fx_tick        ; PAYLOAD_OFF + 3 : called from the main loop
    jmp near fx_audio_isr   ; PAYLOAD_OFF + 6 : called from the sample IRQ

signature:
    db "S1100FX", 0
version:
    db __?UTC_DATE?__, 0    ; build date, shown on the utility page

; --- fx_init ------------------------------------------------------------
; Called once after the stock OS has initialised hardware. Must preserve
; all registers and the direction flag; must return with a near RET.
fx_init:
    pusha
    push ds
    push cs
    pop ds
    ; TODO(milestone 3): initialise FX state, e.g. passthrough settings.
    mov byte [fx_enabled], 0
    pop ds
    popa
    ret

; --- fx_tick --------------------------------------------------------------
; Called from the stock OS main loop. Keep it short: no blocking I/O.
fx_tick:
    ret

; --- fx_audio_isr ---------------------------------------------------------
; Placeholder for real-time processing (milestone 4). Will read the ADC
; and write the DAC once their I/O ports are mapped (see docs/hardware.md).
fx_audio_isr:
    ret

; --- mods ---------------------------------------------------------------------
; Each mod is compiled in only when its spec in mods/ is selected (the spec's
; [defines] table sets MOD_<NAME>). DSP cores are shared and bit-exact with
; tools/vintage.py; see tests/test_dsp.py.

%ifdef MOD_VINTAGE
%include "dsp/presets.inc"
%include "dsp/crush.asm"
%endif
%ifdef MOD_AUTOCHOP
%include "dsp/chop.asm"
%endif

; --- state ------------------------------------------------------------------
fx_enabled:     db 0
