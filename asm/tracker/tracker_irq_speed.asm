; ==========================================================================
; TRACKER IRQ HANDLER - SPEED OPTIMIZED (4-channel, Full Bytes)
; ==========================================================================
; Timer-driven interrupt handler for playing VQ-compressed samples
; with pitch control on 4 independent POKEY channels.
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

; SMC opcodes for dispatch (used by process_row.asm)
OPCODE_BMI = $30            ; BMI: not taken when N=0 (nopitch path)
OPCODE_BPL = $10            ; BPL: taken when N=0 (pitch path)

Tracker_IRQ:
    sta irq_save_a
    stx irq_save_x
    sty irq_save_y
    
    lda #0
    sta IRQEN
    lda #IRQ_MASK
    sta IRQEN
    
    ; =========================================================================
    ; CHANNEL 0 - AUDC1
    ; =========================================================================
    lda trk0_active
    beq @skip_ch0
    
    ldy trk0_vector_offset
.if VOLUME_CONTROL = 1
    lda (trk0_sample_ptr),y
    and #$0F
    ora trk0_vol_shift
    tax
    lda VOLUME_SCALE,x
    sta AUDC1
.else
    lda (trk0_sample_ptr),y
    sta AUDC1
.endif
    
ch0_dispatch = *
    bmi @ch0_pitch

    inc trk0_vector_offset
    lda trk0_vector_offset
    cmp #MIN_VECTOR
    bcc @skip_ch0
    
    lda #0
    sta trk0_vector_offset
    inc trk0_stream_ptr
    bne @ch0_check_end
    inc trk0_stream_ptr+1

@ch0_check_end:
    lda trk0_stream_ptr+1
    cmp trk0_stream_end+1
    bcc @ch0_load_vector
    bne @ch0_end
    lda trk0_stream_ptr
    cmp trk0_stream_end
    bcs @ch0_end

@ch0_load_vector:
    ldy #0
    lda (trk0_stream_ptr),y
    tay
    lda VQ_LO,y
    sta trk0_sample_ptr
    lda VQ_HI,y
    sta trk0_sample_ptr+1
    jmp @skip_ch0

@ch0_end:
    lda #0
    sta trk0_active
    lda #$10
    sta AUDC1
    bpl @skip_ch0

@ch0_pitch:
    clc
    lda trk0_pitch_frac
    adc trk0_pitch_step
    sta trk0_pitch_frac
    lda trk0_pitch_int
    adc trk0_pitch_step+1
    sta trk0_pitch_int
    
    beq @skip_ch0
    
    clc
    lda trk0_vector_offset
    adc trk0_pitch_int
    sta trk0_vector_offset
    
    lda #0
    sta trk0_pitch_int
    
    lda trk0_vector_offset
    cmp #MIN_VECTOR
    bcc @skip_ch0
    
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
    adc trk0_stream_ptr
    sta trk0_stream_ptr
    bcc @ch0_p_nocarry
    inc trk0_stream_ptr+1
@ch0_p_nocarry:
    
    txa
    and #VECTOR_MASK
    sta trk0_vector_offset
    jmp @ch0_check_end

@skip_ch0:

    ; =========================================================================
    ; CHANNEL 1 - AUDC2
    ; =========================================================================
    lda trk1_active
    beq @skip_ch1
    
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
    
ch1_dispatch = *
    bmi @ch1_pitch

    inc trk1_vector_offset
    lda trk1_vector_offset
    cmp #MIN_VECTOR
    bcc @skip_ch1
    
    lda #0
    sta trk1_vector_offset
    inc trk1_stream_ptr
    bne @ch1_check_end
    inc trk1_stream_ptr+1

@ch1_check_end:
    lda trk1_stream_ptr+1
    cmp trk1_stream_end+1
    bcc @ch1_load_vector
    bne @ch1_end
    lda trk1_stream_ptr
    cmp trk1_stream_end
    bcs @ch1_end

@ch1_load_vector:
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
    bpl @skip_ch1

@ch1_pitch:
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
    bcc @ch1_p_nocarry
    inc trk1_stream_ptr+1
@ch1_p_nocarry:
    
    txa
    and #VECTOR_MASK
    sta trk1_vector_offset
    jmp @ch1_check_end

@skip_ch1:

    ; =========================================================================
    ; CHANNEL 2 - AUDC3
    ; =========================================================================
    lda trk2_active
    beq @skip_ch2
    
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
    
ch2_dispatch = *
    bmi @ch2_pitch

    inc trk2_vector_offset
    lda trk2_vector_offset
    cmp #MIN_VECTOR
    bcc @skip_ch2
    
    lda #0
    sta trk2_vector_offset
    inc trk2_stream_ptr
    bne @ch2_check_end
    inc trk2_stream_ptr+1

@ch2_check_end:
    lda trk2_stream_ptr+1
    cmp trk2_stream_end+1
    bcc @ch2_load_vector
    bne @ch2_end
    lda trk2_stream_ptr
    cmp trk2_stream_end
    bcs @ch2_end

@ch2_load_vector:
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
    bpl @skip_ch2

@ch2_pitch:
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
    bcc @ch2_p_nocarry
    inc trk2_stream_ptr+1
@ch2_p_nocarry:
    
    txa
    and #VECTOR_MASK
    sta trk2_vector_offset
    jmp @ch2_check_end

@skip_ch2:

    ; =========================================================================
    ; CHANNEL 3 - AUDC4
    ; =========================================================================
    lda trk3_active
    beq @skip_ch3
    
    ldy trk3_vector_offset
.if VOLUME_CONTROL = 1
    lda (trk3_sample_ptr),y
    and #$0F
    ora trk3_vol_shift
    tax
    lda VOLUME_SCALE,x
    sta AUDC4
.else
    lda (trk3_sample_ptr),y
    sta AUDC4
.endif
    
ch3_dispatch = *
    bmi @ch3_pitch

    inc trk3_vector_offset
    lda trk3_vector_offset
    cmp #MIN_VECTOR
    bcc @skip_ch3
    
    lda #0
    sta trk3_vector_offset
    inc trk3_stream_ptr
    bne @ch3_check_end
    inc trk3_stream_ptr+1

@ch3_check_end:
    lda trk3_stream_ptr+1
    cmp trk3_stream_end+1
    bcc @ch3_load_vector
    bne @ch3_end
    lda trk3_stream_ptr
    cmp trk3_stream_end
    bcs @ch3_end

@ch3_load_vector:
    ldy #0
    lda (trk3_stream_ptr),y
    tay
    lda VQ_LO,y
    sta trk3_sample_ptr
    lda VQ_HI,y
    sta trk3_sample_ptr+1
    jmp @skip_ch3

@ch3_end:
    lda #0
    sta trk3_active
    lda #$10
    sta AUDC4
    bpl @skip_ch3

@ch3_pitch:
    clc
    lda trk3_pitch_frac
    adc trk3_pitch_step
    sta trk3_pitch_frac
    lda trk3_pitch_int
    adc trk3_pitch_step+1
    sta trk3_pitch_int
    
    beq @skip_ch3
    
    clc
    lda trk3_vector_offset
    adc trk3_pitch_int
    sta trk3_vector_offset
    
    lda #0
    sta trk3_pitch_int
    
    lda trk3_vector_offset
    cmp #MIN_VECTOR
    bcc @skip_ch3
    
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
    adc trk3_stream_ptr
    sta trk3_stream_ptr
    bcc @ch3_p_nocarry
    inc trk3_stream_ptr+1
@ch3_p_nocarry:
    
    txa
    and #VECTOR_MASK
    sta trk3_vector_offset
    jmp @ch3_check_end

@skip_ch3:

    ; =========================================================================
    ; EXIT
    ; =========================================================================
    lda irq_save_a
    ldx irq_save_x
    ldy irq_save_y
    rti
