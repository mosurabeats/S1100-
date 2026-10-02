; chop.asm -- auto chop: streaming transient (onset) detector.
;
; Bit-exact with tools/vintage.py (detect / ChopState). Two envelopes in
; 16.16 fixed point, each updated as  env += d * m  with m = 2^(16-k):
;   fast: peak follower of a = |x|/2 (attack m_attack, release m_release)
;   slow: follows fast (m_slow), so steady notes settle at fast ~= slow
; An onset fires when
;     fast - slow > (slow >> ratio_shift) + thresh
; and no onset fired in the last min_gap samples. The slice point snaps back
; to the latest zero crossing if it is within zc_window samples, so slices
; start cleanly before the attack.
;
; The onset list keeps the CH_CAP strongest onsets, in time order (exact
; streaming top-N: when full, a new onset evicts the first-weakest entry
; only if it is strictly stronger).

; struc chop_state
CH_EF       equ 0   ; dword: fast envelope, 16.16 (integer part at +2)
CH_ES       equ 4   ; dword: slow envelope, 16.16
CH_MA       equ 8   ; word: fast attack multiplier  (2^(16-k), k = 2..15)
CH_MR       equ 10  ; word: fast release multiplier
CH_MS       equ 12  ; word: slow multiplier
CH_RS       equ 14  ; byte: ratio shift
CH_PREVNEG  equ 15  ; byte: sign of previous sample (0 or 0x80)
CH_THRESH   equ 16  ; word: absolute threshold (envelope units, 0..16384)
CH_GAP      equ 18  ; word: hold-off samples remaining
CH_MINGAP   equ 20  ; word: hold-off after an onset
CH_ZCWIN    equ 22  ; word: zero-crossing snap window
CH_POS      equ 24  ; dword: index of the next sample
CH_LASTZC   equ 28  ; dword: index of the latest zero crossing
CH_CAP      equ 32  ; word: onset list capacity
CH_COUNT    equ 34  ; word: onsets stored
CH_LIST     equ 36  ; word: DS offset of the list: {dword pos, word strength}
CH_SIZE     equ 38

ONSET_SIZE  equ 6

; chop_process
;   in:  DS:BX -> chop_state, DS:SI -> int16 input, CX = sample count
;   out: SI advanced, CX = 0, list/state updated
;   preserves: BX, BP, DS, ES, direction flag
chop_process:
    pushf
    push bp
    push ax
    push dx
    push di
    cld
    mov bp, cx                      ; bp = samples left
    test bp, bp
    jz .done
.loop:
    lodsw
    mov dl, ah                      ; zero crossing: sign changed?
    and dl, 0x80
    cmp dl, [bx + CH_PREVNEG]
    je .no_zc
    mov [bx + CH_PREVNEG], dl
    mov dx, [bx + CH_POS]
    mov [bx + CH_LASTZC], dx
    mov dx, [bx + CH_POS + 2]
    mov [bx + CH_LASTZC + 2], dx
.no_zc:
    cwd                             ; a = |x| >> 1 (unsigned, 0..16384)
    xor ax, dx
    sub ax, dx
    shr ax, 1
    sub ax, [bx + CH_EF + 2]        ; d = a - fast
    js .release
    imul word [bx + CH_MA]
    jmp .fast
.release:
    imul word [bx + CH_MR]
.fast:
    add [bx + CH_EF], ax
    adc [bx + CH_EF + 2], dx
    mov ax, [bx + CH_EF + 2]        ; slow += (fast - slow) * m_slow
    sub ax, [bx + CH_ES + 2]
    imul word [bx + CH_MS]
    add [bx + CH_ES], ax
    adc [bx + CH_ES + 2], dx
    cmp word [bx + CH_GAP], 0
    je .armed
    dec word [bx + CH_GAP]
    jmp .next
.armed:
    mov ax, [bx + CH_EF + 2]        ; ax = strength = fast - slow
    sub ax, [bx + CH_ES + 2]
    mov dx, [bx + CH_ES + 2]
    mov cl, [bx + CH_RS]
    sar dx, cl
    add dx, [bx + CH_THRESH]
    cmp ax, dx
    jle .next
    mov di, [bx + CH_POS]           ; distance to last zero crossing
    mov dx, [bx + CH_POS + 2]
    sub di, [bx + CH_LASTZC]
    sbb dx, [bx + CH_LASTZC + 2]
    jnz .use_pos
    cmp di, [bx + CH_ZCWIN]
    ja .use_pos
    mov di, [bx + CH_LASTZC]
    mov dx, [bx + CH_LASTZC + 2]
    jmp .add
.use_pos:
    mov di, [bx + CH_POS]
    mov dx, [bx + CH_POS + 2]
.add:
    call chop_add
    mov ax, [bx + CH_MINGAP]
    mov [bx + CH_GAP], ax
.next:
    add word [bx + CH_POS], 1
    adc word [bx + CH_POS + 2], 0
    dec bp
    jnz .loop
.done:
    xor cx, cx
    pop di
    pop dx
    pop ax
    pop bp
    popf
    ret

; chop_add -- insert onset DX:DI with strength AX (internal)
;   clobbers: AX, CX, DX, DI
chop_add:
    push si
    push dx
    push di
    mov si, [bx + CH_LIST]
    mov cx, [bx + CH_COUNT]
    cmp cx, [bx + CH_CAP]
    jb .append
    jcxz .drop                      ; capacity 0
    mov di, si                      ; find first weakest: di = entry, dx = strength
    mov dx, [si + 4]
    dec cx
    jz .found
.scan:
    add si, ONSET_SIZE
    cmp [si + 4], dx
    jge .not_less
    mov dx, [si + 4]
    mov di, si
.not_less:
    loop .scan
.found:
    cmp ax, dx
    jle .drop
    push ax                         ; delete entry at di
    mov ax, [bx + CH_COUNT]
    mov cx, ONSET_SIZE
    mul cx
    add ax, [bx + CH_LIST]          ; ax = end of list
    mov si, di
    add si, ONSET_SIZE
    mov cx, ax
    sub cx, si
    shr cx, 1
    push es
    push ds
    pop es
    rep movsw
    pop es
    pop ax
    dec word [bx + CH_COUNT]
    mov cx, [bx + CH_COUNT]
    mov si, [bx + CH_LIST]
.append:
    push ax
    mov ax, ONSET_SIZE
    mul cx
    add si, ax
    pop ax
    pop di
    pop dx
    mov [si], di
    mov [si + 2], dx
    mov [si + 4], ax
    inc word [bx + CH_COUNT]
    pop si
    ret
.drop:
    pop di
    pop dx
    pop si
    ret
