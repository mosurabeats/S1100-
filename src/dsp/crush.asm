; crush.asm -- vintage sampler emulation: bit reduction + sample-and-hold.
;
; Bit-exact with tools/vintage.py (crush / quantize / CrushState); the tests
; in tests/test_dsp.py run this code in an emulator against that model.
;
; Streaming: the V50 sees 1 MB but sample RAM is 2-32 MB behind the gate
; arrays, so samples are processed in chunks with state carried between
; calls. Any chunk size works and the result equals one big call.

; struc crush_state
CR_MASK     equ 0   ; word: keep-mask for the top `bits` bits
CR_GAIN     equ 2   ; word: pre-gain, Q8 (256 = unity)
CR_STEP     equ 4   ; word: 0.16 phase increment, 0 = latch every sample
CR_ACC      equ 6   ; word: phase accumulator
CR_HELD     equ 8   ; word: current held (quantised) sample
CR_FLAGS    equ 10  ; byte: bit 0 = decimate (emit latched samples only)
CR_SIZE     equ 12

CRF_DECIMATE equ 1

; crush_setup
;   in:  DS:BX -> crush_state, DS:SI -> preset entry (presets.inc layout),
;        AX = source sample rate (Hz)
;   out: state initialised (CR_FLAGS left untouched)
;   clobbers: AX, CX, DX
crush_setup:
    mov cx, ax                      ; cx = source rate
    mov ax, [si + PRESET_GAIN]
    mov [bx + CR_GAIN], ax
    push cx
    mov cl, 16
    sub cl, [si + PRESET_BITS]
    mov ax, 0xFFFF
    shl ax, cl
    mov [bx + CR_MASK], ax
    pop cx
    xor ax, ax                      ; step = 0 unless 0 < rate < source
    mov dx, [si + PRESET_RATE]
    test dx, dx
    jz .store_step
    cmp dx, cx
    jae .zero_step
    div cx                          ; ax = (rate << 16) / source
    jmp .store_step
.zero_step:
    xor ax, ax
.store_step:
    mov [bx + CR_STEP], ax
    mov word [bx + CR_ACC], 0xFFFF  ; first sample always latches
    mov word [bx + CR_HELD], 0
    ret

; crush_process
;   in:  DS:BX -> crush_state, DS:SI -> int16 input, ES:DI -> int16 output,
;        CX = sample count (may be 0)
;   out: AX = samples written, SI/DI advanced, CX = 0
;   preserves: BX, BP, DS, ES, direction flag
crush_process:
    pushf
    push bp
    push dx
    cld
    xor bp, bp
    jcxz .done
.loop:
    lodsw
    mov dx, [bx + CR_STEP]
    test dx, dx
    jz .latch
    add [bx + CR_ACC], dx
    jc .latch
    test byte [bx + CR_FLAGS], CRF_DECIMATE
    jnz .next
    mov ax, [bx + CR_HELD]
    jmp .emit
.latch:
    imul word [bx + CR_GAIN]        ; dx:ax = x * gain
    mov al, ah                      ; ax = (dx:ax) >> 8, low 16 bits
    mov ah, dl
    mov dl, ah                      ; in range iff DH is AH's sign extension
    sar dl, 7
    cmp dl, dh
    je .in_range
    mov ax, 0x7FFF
    test dh, dh
    jns .in_range
    mov ax, 0x8000
.in_range:
    and ax, [bx + CR_MASK]
    mov [bx + CR_HELD], ax
.emit:
    stosw
    inc bp
.next:
    loop .loop
.done:
    mov ax, bp
    pop dx
    pop bp
    popf
    ret
