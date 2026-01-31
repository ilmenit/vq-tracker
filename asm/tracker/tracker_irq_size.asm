; ==========================================================================
; TRACKER IRQ HANDLER - SIZE OPTIMIZED (Nibble-packed)
; ==========================================================================
; Timer-driven interrupt handler for playing VQ-compressed samples
; with pitch control on 3 independent POKEY channels.
;
; SIZE OPTIMIZATION (--optimize size in VQ converter):
;   - Nibble-packed data (2 samples per byte)
;   - Requires LUT for nibble extraction
;   - Uses stream_ptr directly for VQ index fetch (no temp pointer copy)
;   - More compact codebook, slightly more cycles per channel
;
; OPTIMIZATION: Instead of looping for each boundary crossed, we calculate
; the total crosses using division (shifts) and handle all at once.
; This makes high-pitch notes O(1) instead of O(N) where N = crosses.
;
; For MIN_VECTOR = 2, 4, 8, or 16 (powers of 2):
;   crosses = vector_offset >> log2(MIN_VECTOR)
;   new_offset = vector_offset & (MIN_VECTOR - 1)
;
; Features:
;   - 8.8 fixed-point pitch accumulator per channel
;   - LUT-based nibble extraction
;   - O(1) boundary handling using shifts/masks
;   - Optional volume control (.if VOLUME_CONTROL = 1)
;
; Cycle Budget (per channel, OPTIMIZED):
;   - Inactive: 5 cycles
;   - Active (no boundary cross): ~75 cycles
;   - Active (with boundary cross): ~125 cycles
;
; With VOLUME_CONTROL=1: Add ~11 cycles per active channel
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
    lda LUT_NIBBLE_LO,x
    and #$0F
    ora trk0_vol_shift
    tax
    lda VOLUME_SCALE,x
    sta AUDC1
.else
    lda LUT_NIBBLE_LO,x
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
    lda LUT_NIBBLE_HI,x
    sta AUDC1
.endif
    
@ch0_advance:
    ; --- Pitch accumulator (8.8 fixed-point) ---
    clc
    lda trk0_pitch_frac
    adc trk0_pitch_step
    sta trk0_pitch_frac
    lda trk0_pitch_int
    adc trk0_pitch_step+1
    sta trk0_pitch_int
    
    beq @skip_ch0               ; No advancement if pitch_int = 0
    
    ; --- Advance vector_offset by pitch_int samples ---
    clc
    lda trk0_vector_offset
    adc trk0_pitch_int
    sta trk0_vector_offset
    
    lda #0
    sta trk0_pitch_int          ; Reset integer accumulator
    
    ; --- OPTIMIZED BOUNDARY CHECK (O(1), no loop!) ---
    lda trk0_vector_offset
    cmp #MIN_VECTOR
    bcc @skip_ch0               ; No boundary cross? Done.
    
    ; Calculate crosses and new offset using shifts/masks
    ; Save original offset for mask operation
    tax                         ; X = original offset
    
    ; Divide to get number of boundaries crossed
.if MIN_VECTOR = 2
    lsr                         ; A = offset / 2
.elif MIN_VECTOR = 4
    lsr
    lsr                         ; A = offset / 4
.elif MIN_VECTOR = 8
    lsr
    lsr
    lsr                         ; A = offset / 8
.elif MIN_VECTOR = 16
    lsr
    lsr
    lsr
    lsr                         ; A = offset / 16
.endif
    
    ; A = number of boundaries crossed, add to stream_ptr
    clc
    adc trk0_stream_ptr
    sta trk0_stream_ptr
    bcc @ch0_no_carry
    inc trk0_stream_ptr+1
@ch0_no_carry:
    
    ; Calculate new offset: original % MIN_VECTOR
    txa                         ; A = original offset
    and #VECTOR_MASK            ; A = offset mod MIN_VECTOR
    sta trk0_vector_offset
    
    ; Check end of sample (16-bit compare)
    lda trk0_stream_ptr+1
    cmp trk0_stream_end+1
    bcc @ch0_load_vector        ; High byte less = not at end
    bne @ch0_end                ; High byte greater = past end
    lda trk0_stream_ptr
    cmp trk0_stream_end
    bcs @ch0_end                ; Low byte >= end = done
    
@ch0_load_vector:
    ; Load the new VQ vector (optimized: use stream_ptr directly)
    ldy #0
    lda (trk0_stream_ptr),y     ; Get VQ codebook index
    tay
    
    lda VQ_LO,y
    sta trk0_sample_ptr
    lda VQ_HI,y
    sta trk0_sample_ptr+1
    jmp @skip_ch0
    
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
    ora trk2_vol_shift
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
