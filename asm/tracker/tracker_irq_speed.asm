; ==========================================================================
; TRACKER IRQ HANDLER - SPEED OPTIMIZED (Full Bytes)
; ==========================================================================
; Timer-driven interrupt handler for playing VQ-compressed samples
; with pitch control on 3 independent POKEY channels.
;
; SPEED OPTIMIZATION (--optimize speed in VQ converter):
;   - Each sample stored as full byte (not nibble-packed)
;   - $10 (volume-only mode bit) pre-baked into codebook data
;   - Direct load/store - no LUT, no odd/even check
;   - Uses stream_ptr directly for VQ index fetch (no temp pointer copy)
;   - Codebook uses 2x memory but ~60% fewer cycles per channel
;
; Data Format:
;   - Each vector has MIN_VECTOR bytes (not MIN_VECTOR/2)
;   - Each byte = (sample_value & $0F) | $10
;
; Cycle Budget (per channel, verified):
;   - Inactive: 5 cycles
;   - Active (no boundary cross): ~50 cycles
;   - Active (with boundary cross): ~100 cycles
;
; With VOLUME_CONTROL=1: Add ~10 cycles per active channel
;
; ==========================================================================

; Masks for modulo operation (MIN_VECTOR - 1)
.if MIN_VECTOR = 2
    VECTOR_MASK = $01
.elif MIN_VECTOR = 4
    VECTOR_MASK = $03
.elif MIN_VECTOR = 8
    VECTOR_MASK = $07
.elif MIN_VECTOR = 16
    VECTOR_MASK = $0F
.else
    .error "MIN_VECTOR must be 2, 4, 8, or 16"
.endif

Tracker_IRQ:
    ; Save registers (zero-page saves are faster than stack)
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
    
    ; --- OUTPUT at current position (SPEED: direct byte access) ---
    ; In speed mode, each sample is a full byte with $10 pre-baked
    ldy trk0_vector_offset          ; 3 cycles
.if VOLUME_CONTROL = 1
    lda (trk0_sample_ptr),y         ; 5 cycles - load pre-baked byte
    and #$0F                        ; 2 cycles - extract sample value
    ora trk0_vol_shift              ; 3 cycles - combine with volume
    tax                             ; 2 cycles
    lda VOLUME_SCALE,x              ; 4 cycles - scale by volume
    sta AUDC1                       ; 4 cycles
.else
    lda (trk0_sample_ptr),y         ; 5 cycles - load pre-baked byte
    sta AUDC1                       ; 4 cycles - direct store!
.endif
    ; Total output: 12 cycles (no vol) or 23 cycles (with vol)
    ; Compare to size mode: 32-35 cycles!
    
    ; --- Pitch accumulator (8.8 fixed-point) ---
    ; pitch_step is a 16-bit value: high byte = integer part, low byte = fraction
    ; Each IRQ, we add pitch_step to the accumulator (pitch_frac:pitch_int)
    ; The integer part (pitch_int) tells us how many samples to advance
    ;
    ; Example for C-1 (1.0x): pitch_step = $0100
    ;   Each IRQ: pitch_int += $01 -> advance 1 sample
    ; Example for C-4 (8.0x): pitch_step = $0800
    ;   Each IRQ: pitch_int += $08 -> advance 8 samples
    ;
    ; Register state: Y = vector_offset (from output above), A/X = garbage
    clc
    lda trk0_pitch_frac
    adc trk0_pitch_step         ; Add fractional part
    sta trk0_pitch_frac
    lda trk0_pitch_int          ; A = current integer accumulator (should be 0)
    adc trk0_pitch_step+1       ; Add integer part + carry from frac
    sta trk0_pitch_int          ; Store result (flags set from ADC, not STA)
    
    beq @skip_ch0               ; If A=0, no samples to advance (shouldn't happen)
    
    ; --- Advance vector_offset by pitch_int samples ---
    ; After this, vector_offset may exceed MIN_VECTOR (boundary cross)
    clc
    lda trk0_vector_offset      ; A = current position in vector
    adc trk0_pitch_int          ; Add samples to advance
    sta trk0_vector_offset      ; May now be >= MIN_VECTOR
    
    lda #0
    sta trk0_pitch_int          ; Reset integer accumulator for next IRQ
    
    ; --- OPTIMIZED BOUNDARY CHECK (O(1), no loop!) ---
    lda trk0_vector_offset
    cmp #MIN_VECTOR
    bcc @skip_ch0                   ; No boundary cross? Done.
    
    ; Calculate crosses and new offset using shifts/masks
    tax                             ; X = original offset
    
    ; Divide to get number of boundaries crossed
.if MIN_VECTOR = 2
    lsr                             ; A = offset / 2
.elif MIN_VECTOR = 4
    lsr
    lsr                             ; A = offset / 4
.elif MIN_VECTOR = 8
    lsr
    lsr
    lsr                             ; A = offset / 8
.elif MIN_VECTOR = 16
    lsr
    lsr
    lsr
    lsr                             ; A = offset / 16
.endif
    
    ; A = number of boundaries crossed, add to stream_ptr
    clc
    adc trk0_stream_ptr
    sta trk0_stream_ptr
    bcc @ch0_no_carry
    inc trk0_stream_ptr+1
@ch0_no_carry:
    
    ; Calculate new offset: original % MIN_VECTOR
    txa                             ; A = original offset
    and #VECTOR_MASK                ; A = offset mod MIN_VECTOR
    sta trk0_vector_offset
    
    ; Check end of sample (16-bit compare)
    lda trk0_stream_ptr+1
    cmp trk0_stream_end+1
    bcc @ch0_load_vector            ; High byte less = not at end
    bne @ch0_end                    ; High byte greater = past end
    lda trk0_stream_ptr
    cmp trk0_stream_end
    bcs @ch0_end                    ; Low byte >= end = done
    
@ch0_load_vector:
    ; Load the new VQ vector (optimized: use stream_ptr directly)
    ldy #0
    lda (trk0_stream_ptr),y         ; Get VQ codebook index
    tay
    
    lda VQ_LO,y
    sta trk0_sample_ptr
    lda VQ_HI,y
    sta trk0_sample_ptr+1
    jmp @skip_ch0
    
@ch0_end:
    lda #0
    sta trk0_active
    lda #$10                        ; Silence
    sta AUDC1
@skip_ch0:

    ; =========================================================================
    ; CHANNEL 1 - AUDC2
    ; =========================================================================
    lda trk1_active
    beq @skip_ch1
    
    ; --- OUTPUT (SPEED: direct byte access) ---
    ldy trk1_vector_offset
.if VOLUME_CONTROL = 1
    lda (trk1_sample_ptr),y
    and #$0F
    ora trk1_vol_shift
    tax
    lda VOLUME_SCALE,x
    sta AUDC2
.else
    lda (trk1_sample_ptr),y
    sta AUDC2
.endif
    
    ; --- Pitch accumulator ---
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
    
    ; --- OPTIMIZED BOUNDARY CHECK ---
    lda trk1_vector_offset
    cmp #MIN_VECTOR
    bcc @skip_ch1
    
    tax
    
.if MIN_VECTOR = 2
    lsr
.elif MIN_VECTOR = 4
    lsr
    lsr
.elif MIN_VECTOR = 8
    lsr
    lsr
    lsr
.elif MIN_VECTOR = 16
    lsr
    lsr
    lsr
    lsr
.endif
    
    clc
    adc trk1_stream_ptr
    sta trk1_stream_ptr
    bcc @ch1_no_carry
    inc trk1_stream_ptr+1
@ch1_no_carry:
    
    txa
    and #VECTOR_MASK
    sta trk1_vector_offset
    
    lda trk1_stream_ptr+1
    cmp trk1_stream_end+1
    bcc @ch1_load_vector
    bne @ch1_end
    lda trk1_stream_ptr
    cmp trk1_stream_end
    bcs @ch1_end
    
@ch1_load_vector:
    ; Load the new VQ vector (optimized: use stream_ptr directly)
    ldy #0
    lda (trk1_stream_ptr),y
    tay
    
    lda VQ_LO,y
    sta trk1_sample_ptr
    lda VQ_HI,y
    sta trk1_sample_ptr+1
    jmp @skip_ch1
    
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
    
    ; --- OUTPUT (SPEED: direct byte access) ---
    ldy trk2_vector_offset
.if VOLUME_CONTROL = 1
    lda (trk2_sample_ptr),y
    and #$0F
    ora trk2_vol_shift
    tax
    lda VOLUME_SCALE,x
    sta AUDC3
.else
    lda (trk2_sample_ptr),y
    sta AUDC3
.endif
    
    ; --- Pitch accumulator ---
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
    
    ; --- OPTIMIZED BOUNDARY CHECK ---
    lda trk2_vector_offset
    cmp #MIN_VECTOR
    bcc @skip_ch2
    
    tax
    
.if MIN_VECTOR = 2
    lsr
.elif MIN_VECTOR = 4
    lsr
    lsr
.elif MIN_VECTOR = 8
    lsr
    lsr
    lsr
.elif MIN_VECTOR = 16
    lsr
    lsr
    lsr
    lsr
.endif
    
    clc
    adc trk2_stream_ptr
    sta trk2_stream_ptr
    bcc @ch2_no_carry
    inc trk2_stream_ptr+1
@ch2_no_carry:
    
    txa
    and #VECTOR_MASK
    sta trk2_vector_offset
    
    lda trk2_stream_ptr+1
    cmp trk2_stream_end+1
    bcc @ch2_load_vector
    bne @ch2_end
    lda trk2_stream_ptr
    cmp trk2_stream_end
    bcs @ch2_end
    
@ch2_load_vector:
    ; Load the new VQ vector (optimized: use stream_ptr directly)
    ldy #0
    lda (trk2_stream_ptr),y
    tay
    
    lda VQ_LO,y
    sta trk2_sample_ptr
    lda VQ_HI,y
    sta trk2_sample_ptr+1
    jmp @skip_ch2
    
@ch2_end:
    lda #0
    sta trk2_active
    lda #$10
    sta AUDC3
@skip_ch2:

    ; =========================================================================
    ; EXIT
    ; =========================================================================
    lda irq_save_a
    ldx irq_save_x
    ldy irq_save_y
    rti
