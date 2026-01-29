; --- FIXED VQ ALGORITHM ---
; FIXED: ASM-2 - Correct end-of-stream detection using proper unsigned comparison
; FIXED: ASM-7 - Reset nibble_state on loop to prevent wrong nibble playback

fetch_next:
    ; FIX ASM-2: Correct End-of-Stream Detection
    ; Use proper unsigned 16-bit comparison
    ; Old code used BNE which branches for BOTH ptr>end AND ptr<end!
    
    lda stream_ptr+1
    cmp stream_end+1
    bcc @do_fetch           ; ptr_hi < end_hi: definitely safe, continue
    bne @end_reached        ; ptr_hi > end_hi: overrun! stop
    ; High bytes equal, check low bytes
    lda stream_ptr
    cmp stream_end
    bcc @do_fetch           ; ptr_lo < end_lo: safe
    ; ptr_lo >= end_lo: end reached
    
@end_reached:
.ifdef MULTI_SAMPLE
    ; End Reached: Set finished flag and return (don't loop)
    lda #$FF
    sta sample_finished
    rts
.else
    ; End Reached: Loop back to start
    lda #<VQ_INDICES
    sta stream_ptr
    lda #>VQ_INDICES
    sta stream_ptr+1
    
    ; FIX ASM-7: Reset nibble_state for clean loop
    ; Without this, first sample of loop may play wrong nibble
    lda #0
    sta nibble_state
    ; Fall through to do_fetch
.endif

@do_fetch:
    ; Fetch Index
    ldy #0
    lda (stream_ptr),y
    tax ; Codebook Index in X

    ; Advance Stream Ptr
    inc stream_ptr
    bne @skip_inc_hi
    inc stream_ptr+1
@skip_inc_hi:

    ; Lookup params for this Index
    lda VQ_LENS,x
    sta sample_len

    ; VQ_LO[x], VQ_HI[x] -> sample_ptr
    lda VQ_LO,x
    sta sample_ptr
    lda VQ_HI,x
    sta sample_ptr+1
    
    ; Reset Nibble State for Single Channel (Always start new vector at Low Nibble)
    lda #0
    sta nibble_state

play_sample:
    icl "../common/play_routine.asm"

    rts
