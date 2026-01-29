; --- RAW ALGORITHM ---
; FIXED: ASM-2 - Correct end-of-stream detection
; FIXED: ASM-8 - Lightweight loop restart without audio pop

fetch_next_raw:
    ; FIX ASM-2: Correct End-of-Stream Detection
    ; Use proper unsigned 16-bit comparison
    
    lda sample_ptr+1
    cmp stream_end+1
    bcc @do_fetch           ; ptr_hi < end_hi: safe
    bne @end_reached        ; ptr_hi > end_hi: overrun!
    ; High bytes equal, check low bytes
    lda sample_ptr
    cmp stream_end
    bcc @do_fetch           ; ptr_lo < end_lo: safe
    ; ptr_lo >= end_lo: end reached
    
@end_reached:
.ifdef MULTI_SAMPLE
    ; End Reached: Set finished flag
    lda #$FF
    sta sample_finished
    rts
.else
    ; FIX ASM-8: Lightweight restart without full PokeyVQ_Init
    ; Old code: jsr PokeyVQ_Init - causes audible click/pop!
    ; New code: Just reset pointers, skip hardware reinit
    
    lda #<RAW_DATA
    sta sample_ptr
    lda #>RAW_DATA
    sta sample_ptr+1
    
    ; Reset nibble state for clean restart
    lda #0
    sta nibble_state
    
    ; Do NOT call PokeyVQ_Init - that resets POKEY and causes pop!
    ; Fall through to continue playback
.endif

@do_fetch:
    ; Fetch and play sample
    ldy #0
    lda (sample_ptr),y
    
    ; Output based on channel mode
.if CHANNELS == 1
    ; Single channel nibble handling
    lda nibble_state
    bne @do_high_nibble
    
    ; Low nibble
    lda (sample_ptr),y
    and #$0F
    ora #AUDC1_MASK
    sta AUDC1
    inc nibble_state
    rts
    
@do_high_nibble:
    lda (sample_ptr),y
    lsr
    lsr
    lsr
    lsr
    ora #AUDC1_MASK
    sta AUDC1
    
    ; Advance pointer (byte consumed)
    inc sample_ptr
    bne @skip_hi
    inc sample_ptr+1
@skip_hi:
    lda #0
    sta nibble_state
    rts
    
.else
    ; Dual channel packed mode
    lda (sample_ptr),y
    tax
    
    ; Low nibble -> Ch1
    and #$0F
    ora #AUDC1_MASK
    tay
    
    ; High nibble -> Ch2
    txa
    lsr
    lsr
    lsr
    lsr
    ora #AUDC2_MASK
    
    ; Commit to POKEY
    sty AUDC1
    sta AUDC2
    
    ; Advance pointer
    inc sample_ptr
    bne @skip_hi_dual
    inc sample_ptr+1
@skip_hi_dual:
    rts
.endif
