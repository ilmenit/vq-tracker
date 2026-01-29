; ==========================================================================
; TRACKER IRQ HANDLER - 3-Channel Sample Playback
; ==========================================================================
; Timer-driven interrupt handler for playing VQ-compressed samples
; with pitch control on 3 independent POKEY channels.
;
; Features:
;   - 8.8 fixed-point pitch accumulator per channel
;   - LUT-based nibble extraction (saves ~5 cycles/sample)
;   - Boundary loop for high-pitch notes that skip multiple vectors
;   - Output BEFORE advance ensures sample 0 is played
;   - Optional volume control (.if VOLUME_CONTROL = 1)
;
; Data Format:
;   - 16 samples per VQ vector = 8 bytes (nibble-packed)
;   - Byte N contains: [sample 2N+1 : sample 2N] (high:low nibbles)
;
; Cycle Budget (per channel, typical, NO volume control):
;   - Active check: ~5 cycles
;   - Nibble output with LUT: ~25 cycles
;   - Pitch advance: ~25 cycles
;   - Boundary check: ~10 cycles
;   - Total: ~65 cycles/channel = ~195 cycles for 3 channels
;
; With VOLUME_CONTROL=1: Add ~13 cycles per active channel
;
; ==========================================================================

.if VOLUME_CONTROL = 1
; Volume scaling lookup table: VOLUME_SCALE[sample + vol_shifted]
; Where sample = 0-15, vol_shifted = volume * 16 (0, 16, 32, ... 240)
; Result = (sample * volume / 15) | $10
; This is 256 bytes, placed after IRQ code
.endif

Tracker_IRQ:
    ; Save registers
    sta irq_save_a
    stx irq_save_x
    sty irq_save_y
    
    ; Acknowledge IRQ (reset timer)
    lda #0
    sta IRQEN
    lda #IRQ_MASK
    sta IRQEN
    
    ; =========================================================================
    ; CHANNEL 0 - AUDC1
    ; =========================================================================
    lda trk0_active
    beq @skip_ch0
    
    ; --- OUTPUT at current position (using LUT) ---
    lda trk0_vector_offset
    lsr                         ; byte_offset = sample / 2
    tay
    
    lda (trk0_sample_ptr),y     ; Load packed byte
    tax                         ; X = packed byte for LUT index
    
    lda trk0_vector_offset
    and #$01                    ; Check odd/even
    bne @ch0_high
    
@ch0_low:
.if VOLUME_CONTROL = 1
    ; Volume scaling: get raw nibble, combine with volume, lookup scaled
    lda LUT_NIBBLE_LO,x         ; Get low nibble (0-15, no $10 mask yet)
    and #$0F                    ; Ensure just nibble
    ora trk0_vol_shift          ; Combine with volume (vol * 16)
    tax
    lda VOLUME_SCALE,x          ; Look up scaled value (includes $10)
    sta AUDC1
.else
    lda LUT_NIBBLE_LO,x         ; Low nibble + $10 mask
    sta AUDC1
.endif
    jmp @ch0_advance
    
@ch0_high:
.if VOLUME_CONTROL = 1
    lda LUT_NIBBLE_HI,x
    and #$0F
    ora trk0_vol_shift
    tax
    lda VOLUME_SCALE,x
    sta AUDC1
.else
    lda LUT_NIBBLE_HI,x         ; High nibble + $10 mask
    sta AUDC1
.endif
    
@ch0_advance:
    ; --- Pitch accumulator (8.8 fixed-point) ---
    clc
    lda trk0_pitch_frac
    adc trk0_pitch_step         ; Add fractional part
    sta trk0_pitch_frac
    lda trk0_pitch_int
    adc trk0_pitch_step+1       ; Add integer part with carry
    sta trk0_pitch_int
    
    beq @skip_ch0               ; No advancement if pitch_int = 0
    
    ; --- Advance vector_offset by pitch_int samples ---
    clc
    lda trk0_vector_offset
    adc trk0_pitch_int
    sta trk0_vector_offset
    
    lda #0
    sta trk0_pitch_int          ; Reset integer accumulator
    
    ; --- Check vector boundary (with loop for high pitches) ---
@ch0_check_boundary:
    lda trk0_vector_offset
    cmp #MIN_VECTOR
    bcc @skip_ch0               ; Still within current vector
    
    ; Crossed boundary - wrap and advance stream
    sec
    sbc #MIN_VECTOR
    sta trk0_vector_offset
    
    ; Advance stream pointer
    inc trk0_stream_ptr
    bne @ch0_check_end
    inc trk0_stream_ptr+1
    
@ch0_check_end:
    ; 16-bit end-of-sample check
    lda trk0_stream_ptr+1
    cmp trk0_stream_end+1
    bcc @ch0_update_cache       ; High byte less = not at end
    bne @ch0_end                ; High byte greater = past end
    lda trk0_stream_ptr
    cmp trk0_stream_end
    bcs @ch0_end                ; Low byte >= end = done
    
@ch0_update_cache:
    ; Load next VQ vector
    lda trk0_stream_ptr
    sta trk_ptr
    lda trk0_stream_ptr+1
    sta trk_ptr+1
    
    ldy #0
    lda (trk_ptr),y             ; Get VQ codebook index
    tay
    
    lda VQ_LO,y
    sta trk0_sample_ptr
    lda VQ_HI,y
    sta trk0_sample_ptr+1
    
    jmp @ch0_check_boundary     ; Check if more vectors to skip (high pitch)
    
@ch0_end:
    lda #0
    sta trk0_active
    lda #$10                    ; Silence
    sta AUDC1
@skip_ch0:

    ; =========================================================================
    ; CHANNEL 1 - AUDC2
    ; =========================================================================
    lda trk1_active
    beq @skip_ch1
    
    lda trk1_vector_offset
    lsr
    tay
    
    lda (trk1_sample_ptr),y
    tax
    
    lda trk1_vector_offset
    and #$01
    bne @ch1_high
    
@ch1_low:
.if VOLUME_CONTROL = 1
    lda LUT_NIBBLE_LO,x
    and #$0F
    ora trk1_vol_shift
    tax
    lda VOLUME_SCALE,x
    sta AUDC2
.else
    lda LUT_NIBBLE_LO,x
    sta AUDC2
.endif
    jmp @ch1_advance
    
@ch1_high:
.if VOLUME_CONTROL = 1
    lda LUT_NIBBLE_HI,x
    and #$0F
    ora trk1_vol_shift
    tax
    lda VOLUME_SCALE,x
    sta AUDC2
.else
    lda LUT_NIBBLE_HI,x
    sta AUDC2
.endif
    
@ch1_advance:
    clc
    lda trk1_pitch_frac
    adc trk1_pitch_step
    sta trk1_pitch_frac
    lda trk1_pitch_int
    adc trk1_pitch_step+1
    sta trk1_pitch_int
    
    beq @skip_ch1
    
    clc
    lda trk1_vector_offset
    adc trk1_pitch_int
    sta trk1_vector_offset
    
    lda #0
    sta trk1_pitch_int
    
@ch1_check_boundary:
    lda trk1_vector_offset
    cmp #MIN_VECTOR
    bcc @skip_ch1
    
    sec
    sbc #MIN_VECTOR
    sta trk1_vector_offset
    
    inc trk1_stream_ptr
    bne @ch1_check_end
    inc trk1_stream_ptr+1
    
@ch1_check_end:
    lda trk1_stream_ptr+1
    cmp trk1_stream_end+1
    bcc @ch1_update_cache
    bne @ch1_end
    lda trk1_stream_ptr
    cmp trk1_stream_end
    bcs @ch1_end
    
@ch1_update_cache:
    lda trk1_stream_ptr
    sta trk_ptr
    lda trk1_stream_ptr+1
    sta trk_ptr+1
    
    ldy #0
    lda (trk_ptr),y
    tay
    
    lda VQ_LO,y
    sta trk1_sample_ptr
    lda VQ_HI,y
    sta trk1_sample_ptr+1
    
    jmp @ch1_check_boundary
    
@ch1_end:
    lda #0
    sta trk1_active
    lda #$10
    sta AUDC2
@skip_ch1:

    ; =========================================================================
    ; CHANNEL 2 - AUDC3
    ; =========================================================================
    lda trk2_active
    beq @skip_ch2
    
    lda trk2_vector_offset
    lsr
    tay
    
    lda (trk2_sample_ptr),y
    tax
    
    lda trk2_vector_offset
    and #$01
    bne @ch2_high
    
@ch2_low:
.if VOLUME_CONTROL = 1
    lda LUT_NIBBLE_LO,x
    and #$0F
    ora trk2_vol_shift          ; Regular memory, not ZP
    tax
    lda VOLUME_SCALE,x
    sta AUDC3
.else
    lda LUT_NIBBLE_LO,x
    sta AUDC3
.endif
    jmp @ch2_advance
    
@ch2_high:
.if VOLUME_CONTROL = 1
    lda LUT_NIBBLE_HI,x
    and #$0F
    ora trk2_vol_shift
    tax
    lda VOLUME_SCALE,x
    sta AUDC3
.else
    lda LUT_NIBBLE_HI,x
    sta AUDC3
.endif
    
@ch2_advance:
    clc
    lda trk2_pitch_frac
    adc trk2_pitch_step
    sta trk2_pitch_frac
    lda trk2_pitch_int
    adc trk2_pitch_step+1
    sta trk2_pitch_int
    
    beq @skip_ch2
    
    clc
    lda trk2_vector_offset
    adc trk2_pitch_int
    sta trk2_vector_offset
    
    lda #0
    sta trk2_pitch_int
    
@ch2_check_boundary:
    lda trk2_vector_offset
    cmp #MIN_VECTOR
    bcc @skip_ch2
    
    sec
    sbc #MIN_VECTOR
    sta trk2_vector_offset
    
    inc trk2_stream_ptr
    bne @ch2_check_end
    inc trk2_stream_ptr+1
    
@ch2_check_end:
    lda trk2_stream_ptr+1
    cmp trk2_stream_end+1
    bcc @ch2_update_cache
    bne @ch2_end
    lda trk2_stream_ptr
    cmp trk2_stream_end
    bcs @ch2_end
    
@ch2_update_cache:
    lda trk2_stream_ptr
    sta trk_ptr
    lda trk2_stream_ptr+1
    sta trk_ptr+1
    
    ldy #0
    lda (trk_ptr),y
    tay
    
    lda VQ_LO,y
    sta trk2_sample_ptr
    lda VQ_HI,y
    sta trk2_sample_ptr+1
    
    jmp @ch2_check_boundary
    
@ch2_end:
    lda #0
    sta trk2_active
    lda #$10
    sta AUDC3
@skip_ch2:

    ; =========================================================================
    ; EXIT - Restore registers
    ; =========================================================================
    lda irq_save_a
    ldx irq_save_x
    ldy irq_save_y
    rti
