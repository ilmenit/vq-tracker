; --- PLAYBACK ROUTINE ---
; Handles actual sample playback for both single and dual channel modes.
; FIXED: ASM-3 - Added explicit RTS for CHANNELS==2 mode

.if CHANNELS == 1
    ; --- SINGLE CHANNEL PLAYBACK ---
    ; Uses nibble packing (2 samples per byte)
    
    lda nibble_state
    bne do_high_nibble
    jmp do_low_nibble

do_high_nibble:
    ; Frame T+1 (High Nibble)
    ldy #0
    lda (sample_ptr),y
    
    .ifdef USE_FAST_CPU
        tax
        lda LUT_HI,x
        sta AUDC1
    .else
        lsr
        lsr
        lsr
        lsr
        ora #AUDC1_MASK
        sta AUDC1
    .endif
    
    ; Advance Pointer (Byte consumed)
    inc sample_ptr
    bne @+
    inc sample_ptr+1
@:   
    dec sample_len
    lda #0
    sta nibble_state
    ; Done for this interrupt
    rts

do_low_nibble:
    ; Frame T (Low Nibble)
    ldy #0
    lda (sample_ptr),y
    
    .ifdef USE_FAST_CPU
        tax
        lda LUT_LO,x
        sta AUDC1
    .else
        and #$0F
        ora #AUDC1_MASK
        sta AUDC1
    .endif
    
    ; Prepare for next frame
    dec sample_len
    inc nibble_state
    rts
    
.else ; CHANNELS == 2
    ; --- DUAL CHANNEL PLAYBACK ---

.ifdef USE_FAST_CPU
    ; --- FAST PLAYBACK (Interleaved 5-bit) ---
    ; Fetch 2 pre-calculated bytes per sample
    
    ldy #0
    lda (sample_ptr),y
    sta AUDC1
    
    iny
    lda (sample_ptr),y
    sta AUDC2
    
    ; Advance Vector by 2 bytes
    clc
    lda sample_ptr
    adc #2
    sta sample_ptr
    bcc skip_ptr_hi_fast
    inc sample_ptr+1
skip_ptr_hi_fast:
    dec sample_len
    ; FIX ASM-3: Explicit RTS was missing!
    rts

.else
    ; --- STANDARD PLAYBACK (Packed) ---
    ; 1 byte per sample (Packed Lo/Hi nibbles)
    
    ldy #0
    lda (sample_ptr),y
    
    ; Output to POKEY
    ; High Nibble -> Ch2 (Vol Only)
    ; Low Nibble  -> Ch1 (Vol Only)
    
    tax ; Save Byte in X (High Nibble + Low)
    
    ; Prepare Ch1 in Y
    and #$0F
    ora #AUDC1_MASK
    tay
    
    ; Prepare Ch2 in A
    txa ; Restore Byte
    lsr
    lsr
    lsr
    lsr
    ora #AUDC2_MASK
    ; A now holds Ch2 Value
    
    ; Commit to POKEY
    sty AUDC1   
    sta AUDC2   
    
    ; Advance Vector by 1 byte
    inc sample_ptr
    bne skip_ptr_hi_std
    inc sample_ptr+1
skip_ptr_hi_std:
    dec sample_len
    ; FIX ASM-3: Explicit RTS was missing!
    rts
.endif

.endif
