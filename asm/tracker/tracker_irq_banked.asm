; ==========================================================================
; TRACKER IRQ HANDLER - BANKED (4-channel, Mixed RAW/VQ, Extended Memory)
; ==========================================================================
; Optimized variant with unified mode+pitch dispatch (single SMC JMP).
;
; RAW optimization: the pitch accumulator adds step_hi directly to
; vector_offset, with carry detecting page (256-byte) boundaries.
; This eliminates pitch_int as a middleman for RAW channels, saving
; ~25 cycles per active RAW channel per IRQ (~100 cycles for 4ch).
;
; Layout: each channel's RAW pitch handler is placed immediately
; before chN_skip so the common (no page cross) path falls through
; with zero branch/jump overhead.
;
; SMC per channel (set by process_row.asm):
;   chN_bank     - PORTB value for sample bank
;   chN_tick_jmp - JMP target: one of 4 mode+pitch handlers
;
; Handler targets:
;   chN_raw_pitch    - RAW with pitch (placed before chN_skip)
;   chN_raw_no_pitch - RAW without pitch
;   chN_vq_pitch     - VQ with pitch
;   chN_vq_no_pitch  - VQ without pitch
;
; Cycle counts (common non-boundary path per channel, VOLUME_CONTROL=0):
;   RAW pitch, no page cross: ~25 cycles (was ~50)
;   RAW no-pitch, no wrap:    ~28 cycles (was ~41)
;   VQ no-pitch, no boundary: ~34 cycles (unchanged)
;   Inactive channel:          8 cycles
; ==========================================================================

.ifndef USE_BANKING
    .error "tracker_irq_banked.asm requires USE_BANKING to be defined"
.endif

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

.ifndef OPCODE_BMI
    OPCODE_BMI = $30
.endif
.ifndef OPCODE_BPL
    OPCODE_BPL = $10
.endif
.ifndef OPCODE_BCS
    OPCODE_BCS = $B0
.endif
.ifndef OPCODE_BEQ
    OPCODE_BEQ = $F0
.endif
.ifndef PORTB_MAIN
    PORTB_MAIN = $FE
.endif

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
    bne ch0_active
    jmp ch0_skip
ch0_active:
    
    ; --- Bank switch + Output sample ---
ch0_bank = *+1
    ldx #PORTB_MAIN              ; SMC: patched to instrument's PORTB
    stx PORTB
    
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
    
    ; --- Unified mode+pitch dispatch ---
ch0_tick_jmp = *+1
    jmp ch0_raw_pitch            ; SMC: one of 4 handler targets

    ; --- VQ no-pitch ---
ch0_vq_no_pitch:
    inc trk0_vector_offset
    lda trk0_vector_offset
    cmp #MIN_VECTOR
    bcs ch0_vq_boundary
    jmp ch0_skip

    ; --- VQ pitch ---
ch0_vq_pitch:
    clc
    lda trk0_pitch_frac
    adc trk0_pitch_step
    sta trk0_pitch_frac
    lda trk0_pitch_int
    adc trk0_pitch_step+1
    sta trk0_pitch_int
    beq ch0_vq_pitch_done
    clc
    lda trk0_vector_offset
    adc trk0_pitch_int
    sta trk0_vector_offset
    lda #0
    sta trk0_pitch_int
    lda trk0_vector_offset
    cmp #MIN_VECTOR
    bcc ch0_vq_pitch_done
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
    bcc ch0_vq_p_nc
    inc trk0_stream_ptr+1
    lda trk0_stream_ptr+1
    cmp #$80
    bcc ch0_vq_p_nc
    lda ch0_banks_left
    bne *+5
    jmp ch0_end
    lda #$40
    sta trk0_stream_ptr+1
    inc ch0_bank_seq_idx
    ldy ch0_bank_seq_idx
    lda SAMPLE_BANK_SEQ,y
    sta ch0_bank
    sta PORTB
    dec ch0_banks_left
ch0_vq_p_nc:
    txa
    and #VECTOR_MASK
    sta trk0_vector_offset
    jmp ch0_check_end
ch0_vq_pitch_done:
    jmp ch0_skip

    ; --- VQ boundary (no-pitch path crossed MIN_VECTOR) ---
ch0_vq_boundary:
    lda #0
    sta trk0_vector_offset
    inc trk0_stream_ptr
    bne ch0_check_end
    inc trk0_stream_ptr+1
    lda trk0_stream_ptr+1
    cmp #$80
    bcc ch0_check_end
    lda ch0_banks_left
    bne *+5
    jmp ch0_end
    lda #$40
    sta trk0_stream_ptr+1
    inc ch0_bank_seq_idx
    ldx ch0_bank_seq_idx
    lda SAMPLE_BANK_SEQ,x
    sta ch0_bank
    sta PORTB
    dec ch0_banks_left
    jmp ch0_load_vector

ch0_check_end:
    lda ch0_banks_left
    bne ch0_load_vector
    lda trk0_stream_ptr+1
    cmp trk0_stream_end+1
    bcc ch0_load_vector
    bne ch0_end
    lda trk0_stream_ptr
    cmp trk0_stream_end
    bcs ch0_end

ch0_load_vector:
    ldy #0
    lda (trk0_stream_ptr),y
    tay
    lda VQ_LO,y
    sta trk0_sample_ptr
    lda VQ_HI,y
    sta trk0_sample_ptr+1
    jmp ch0_skip

ch0_end:
    lda #0
    sta trk0_active
    lda #$10
    sta AUDC1
    jmp ch0_skip

    ; --- RAW no-pitch ---
ch0_raw_no_pitch:
    inc trk0_vector_offset       ; 5
    beq ch0_raw_np_page          ; 2 (not taken 255/256)
    jmp ch0_skip                 ; 3

    ; --- RAW page cross (shared by no-pitch and pitch) ---
ch0_raw_np_page:
    inc trk0_sample_ptr+1
    jmp ch0_raw_page_check
ch0_raw_p_page:
    inc trk0_sample_ptr+1
ch0_raw_page_check:
    lda trk0_sample_ptr+1
    cmp #$80
    bcs ch0_raw_bank_cross
    ldx ch0_banks_left          ; X test, preserves A=sample_ptr+1
    bne ch0_raw_page_ok
    cmp trk0_stream_end+1        ; A still = sample_ptr+1
    bcc ch0_raw_page_ok
    jmp ch0_end
ch0_raw_bank_cross:
    lda ch0_banks_left
    bne *+5
    jmp ch0_end
    lda #$40
    sta trk0_sample_ptr+1
    inc ch0_bank_seq_idx
    ldx ch0_bank_seq_idx
    lda SAMPLE_BANK_SEQ,x
    sta ch0_bank
    sta PORTB
    dec ch0_banks_left
ch0_raw_page_ok:
    jmp ch0_skip

    ; --- RAW pitch (HOT PATH — falls through to ch0_skip!) ---
ch0_raw_pitch:
    clc                          ; 2
    lda trk0_pitch_frac          ; 3
    adc trk0_pitch_step          ; 3
    sta trk0_pitch_frac          ; 3
    lda trk0_vector_offset       ; 3
    adc trk0_pitch_step+1        ; 3  (+carry from frac)
    sta trk0_vector_offset       ; 3
    bcs ch0_raw_p_page           ; 2  (not taken → fall through!)

ch0_skip:

    ; =========================================================================
    ; CHANNEL 1 - AUDC2
    ; =========================================================================
    lda trk1_active
    bne ch1_active
    jmp ch1_skip
ch1_active:
ch1_bank = *+1
    ldx #PORTB_MAIN
    stx PORTB
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
ch1_tick_jmp = *+1
    jmp ch1_raw_pitch

ch1_vq_no_pitch:
    inc trk1_vector_offset
    lda trk1_vector_offset
    cmp #MIN_VECTOR
    bcs ch1_vq_boundary
    jmp ch1_skip

ch1_vq_pitch:
    clc
    lda trk1_pitch_frac
    adc trk1_pitch_step
    sta trk1_pitch_frac
    lda trk1_pitch_int
    adc trk1_pitch_step+1
    sta trk1_pitch_int
    beq ch1_vq_pitch_done
    clc
    lda trk1_vector_offset
    adc trk1_pitch_int
    sta trk1_vector_offset
    lda #0
    sta trk1_pitch_int
    lda trk1_vector_offset
    cmp #MIN_VECTOR
    bcc ch1_vq_pitch_done
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
    bcc ch1_vq_p_nc
    inc trk1_stream_ptr+1
    lda trk1_stream_ptr+1
    cmp #$80
    bcc ch1_vq_p_nc
    lda ch1_banks_left
    bne *+5
    jmp ch1_end
    lda #$40
    sta trk1_stream_ptr+1
    inc ch1_bank_seq_idx
    ldy ch1_bank_seq_idx
    lda SAMPLE_BANK_SEQ,y
    sta ch1_bank
    sta PORTB
    dec ch1_banks_left
ch1_vq_p_nc:
    txa
    and #VECTOR_MASK
    sta trk1_vector_offset
    jmp ch1_check_end
ch1_vq_pitch_done:
    jmp ch1_skip

ch1_vq_boundary:
    lda #0
    sta trk1_vector_offset
    inc trk1_stream_ptr
    bne ch1_check_end
    inc trk1_stream_ptr+1
    lda trk1_stream_ptr+1
    cmp #$80
    bcc ch1_check_end
    lda ch1_banks_left
    bne *+5
    jmp ch1_end
    lda #$40
    sta trk1_stream_ptr+1
    inc ch1_bank_seq_idx
    ldx ch1_bank_seq_idx
    lda SAMPLE_BANK_SEQ,x
    sta ch1_bank
    sta PORTB
    dec ch1_banks_left
    jmp ch1_load_vector
ch1_check_end:
    lda ch1_banks_left
    bne ch1_load_vector
    lda trk1_stream_ptr+1
    cmp trk1_stream_end+1
    bcc ch1_load_vector
    bne ch1_end
    lda trk1_stream_ptr
    cmp trk1_stream_end
    bcs ch1_end
ch1_load_vector:
    ldy #0
    lda (trk1_stream_ptr),y
    tay
    lda VQ_LO,y
    sta trk1_sample_ptr
    lda VQ_HI,y
    sta trk1_sample_ptr+1
    jmp ch1_skip
ch1_end:
    lda #0
    sta trk1_active
    lda #$10
    sta AUDC2
    jmp ch1_skip

ch1_raw_no_pitch:
    inc trk1_vector_offset
    beq ch1_raw_np_page
    jmp ch1_skip

ch1_raw_np_page:
    inc trk1_sample_ptr+1
    jmp ch1_raw_page_check
ch1_raw_p_page:
    inc trk1_sample_ptr+1
ch1_raw_page_check:
    lda trk1_sample_ptr+1
    cmp #$80
    bcs ch1_raw_bank_cross
    ldx ch1_banks_left          ; X test, preserves A=sample_ptr+1
    bne ch1_raw_page_ok
    cmp trk1_stream_end+1        ; A still = sample_ptr+1
    bcc ch1_raw_page_ok
    jmp ch1_end
ch1_raw_bank_cross:
    lda ch1_banks_left
    bne *+5
    jmp ch1_end
    lda #$40
    sta trk1_sample_ptr+1
    inc ch1_bank_seq_idx
    ldx ch1_bank_seq_idx
    lda SAMPLE_BANK_SEQ,x
    sta ch1_bank
    sta PORTB
    dec ch1_banks_left
ch1_raw_page_ok:
    jmp ch1_skip

ch1_raw_pitch:
    clc
    lda trk1_pitch_frac
    adc trk1_pitch_step
    sta trk1_pitch_frac
    lda trk1_vector_offset
    adc trk1_pitch_step+1
    sta trk1_vector_offset
    bcs ch1_raw_p_page

ch1_skip:

    ; =========================================================================
    ; CHANNEL 2 - AUDC3
    ; =========================================================================
    lda trk2_active
    bne ch2_active
    jmp ch2_skip
ch2_active:
ch2_bank = *+1
    ldx #PORTB_MAIN
    stx PORTB
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
ch2_tick_jmp = *+1
    jmp ch2_raw_pitch

ch2_vq_no_pitch:
    inc trk2_vector_offset
    lda trk2_vector_offset
    cmp #MIN_VECTOR
    bcs ch2_vq_boundary
    jmp ch2_skip

ch2_vq_pitch:
    clc
    lda trk2_pitch_frac
    adc trk2_pitch_step
    sta trk2_pitch_frac
    lda trk2_pitch_int
    adc trk2_pitch_step+1
    sta trk2_pitch_int
    beq ch2_vq_pitch_done
    clc
    lda trk2_vector_offset
    adc trk2_pitch_int
    sta trk2_vector_offset
    lda #0
    sta trk2_pitch_int
    lda trk2_vector_offset
    cmp #MIN_VECTOR
    bcc ch2_vq_pitch_done
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
    bcc ch2_vq_p_nc
    inc trk2_stream_ptr+1
    lda trk2_stream_ptr+1
    cmp #$80
    bcc ch2_vq_p_nc
    lda ch2_banks_left
    bne *+5
    jmp ch2_end
    lda #$40
    sta trk2_stream_ptr+1
    inc ch2_bank_seq_idx
    ldy ch2_bank_seq_idx
    lda SAMPLE_BANK_SEQ,y
    sta ch2_bank
    sta PORTB
    dec ch2_banks_left
ch2_vq_p_nc:
    txa
    and #VECTOR_MASK
    sta trk2_vector_offset
    jmp ch2_check_end
ch2_vq_pitch_done:
    jmp ch2_skip

ch2_vq_boundary:
    lda #0
    sta trk2_vector_offset
    inc trk2_stream_ptr
    bne ch2_check_end
    inc trk2_stream_ptr+1
    lda trk2_stream_ptr+1
    cmp #$80
    bcc ch2_check_end
    lda ch2_banks_left
    bne *+5
    jmp ch2_end
    lda #$40
    sta trk2_stream_ptr+1
    inc ch2_bank_seq_idx
    ldx ch2_bank_seq_idx
    lda SAMPLE_BANK_SEQ,x
    sta ch2_bank
    sta PORTB
    dec ch2_banks_left
    jmp ch2_load_vector
ch2_check_end:
    lda ch2_banks_left
    bne ch2_load_vector
    lda trk2_stream_ptr+1
    cmp trk2_stream_end+1
    bcc ch2_load_vector
    bne ch2_end
    lda trk2_stream_ptr
    cmp trk2_stream_end
    bcs ch2_end
ch2_load_vector:
    ldy #0
    lda (trk2_stream_ptr),y
    tay
    lda VQ_LO,y
    sta trk2_sample_ptr
    lda VQ_HI,y
    sta trk2_sample_ptr+1
    jmp ch2_skip
ch2_end:
    lda #0
    sta trk2_active
    lda #$10
    sta AUDC3
    jmp ch2_skip

ch2_raw_no_pitch:
    inc trk2_vector_offset
    beq ch2_raw_np_page
    jmp ch2_skip

ch2_raw_np_page:
    inc trk2_sample_ptr+1
    jmp ch2_raw_page_check
ch2_raw_p_page:
    inc trk2_sample_ptr+1
ch2_raw_page_check:
    lda trk2_sample_ptr+1
    cmp #$80
    bcs ch2_raw_bank_cross
    ldx ch2_banks_left          ; X test, preserves A=sample_ptr+1
    bne ch2_raw_page_ok
    cmp trk2_stream_end+1        ; A still = sample_ptr+1
    bcc ch2_raw_page_ok
    jmp ch2_end
ch2_raw_bank_cross:
    lda ch2_banks_left
    bne *+5
    jmp ch2_end
    lda #$40
    sta trk2_sample_ptr+1
    inc ch2_bank_seq_idx
    ldx ch2_bank_seq_idx
    lda SAMPLE_BANK_SEQ,x
    sta ch2_bank
    sta PORTB
    dec ch2_banks_left
ch2_raw_page_ok:
    jmp ch2_skip

ch2_raw_pitch:
    clc
    lda trk2_pitch_frac
    adc trk2_pitch_step
    sta trk2_pitch_frac
    lda trk2_vector_offset
    adc trk2_pitch_step+1
    sta trk2_vector_offset
    bcs ch2_raw_p_page

ch2_skip:

    ; =========================================================================
    ; CHANNEL 3 - AUDC4
    ; =========================================================================
    lda trk3_active
    bne ch3_active
    jmp ch3_skip
ch3_active:
ch3_bank = *+1
    ldx #PORTB_MAIN
    stx PORTB
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
ch3_tick_jmp = *+1
    jmp ch3_raw_pitch

ch3_vq_no_pitch:
    inc trk3_vector_offset
    lda trk3_vector_offset
    cmp #MIN_VECTOR
    bcs ch3_vq_boundary
    jmp ch3_skip

ch3_vq_pitch:
    clc
    lda trk3_pitch_frac
    adc trk3_pitch_step
    sta trk3_pitch_frac
    lda trk3_pitch_int
    adc trk3_pitch_step+1
    sta trk3_pitch_int
    beq ch3_vq_pitch_done
    clc
    lda trk3_vector_offset
    adc trk3_pitch_int
    sta trk3_vector_offset
    lda #0
    sta trk3_pitch_int
    lda trk3_vector_offset
    cmp #MIN_VECTOR
    bcc ch3_vq_pitch_done
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
    bcc ch3_vq_p_nc
    inc trk3_stream_ptr+1
    lda trk3_stream_ptr+1
    cmp #$80
    bcc ch3_vq_p_nc
    lda ch3_banks_left
    bne *+5
    jmp ch3_end
    lda #$40
    sta trk3_stream_ptr+1
    inc ch3_bank_seq_idx
    ldy ch3_bank_seq_idx
    lda SAMPLE_BANK_SEQ,y
    sta ch3_bank
    sta PORTB
    dec ch3_banks_left
ch3_vq_p_nc:
    txa
    and #VECTOR_MASK
    sta trk3_vector_offset
    jmp ch3_check_end
ch3_vq_pitch_done:
    jmp ch3_skip

ch3_vq_boundary:
    lda #0
    sta trk3_vector_offset
    inc trk3_stream_ptr
    bne ch3_check_end
    inc trk3_stream_ptr+1
    lda trk3_stream_ptr+1
    cmp #$80
    bcc ch3_check_end
    lda ch3_banks_left
    bne *+5
    jmp ch3_end
    lda #$40
    sta trk3_stream_ptr+1
    inc ch3_bank_seq_idx
    ldx ch3_bank_seq_idx
    lda SAMPLE_BANK_SEQ,x
    sta ch3_bank
    sta PORTB
    dec ch3_banks_left
    jmp ch3_load_vector
ch3_check_end:
    lda ch3_banks_left
    bne ch3_load_vector
    lda trk3_stream_ptr+1
    cmp trk3_stream_end+1
    bcc ch3_load_vector
    bne ch3_end
    lda trk3_stream_ptr
    cmp trk3_stream_end
    bcs ch3_end
ch3_load_vector:
    ldy #0
    lda (trk3_stream_ptr),y
    tay
    lda VQ_LO,y
    sta trk3_sample_ptr
    lda VQ_HI,y
    sta trk3_sample_ptr+1
    jmp ch3_skip
ch3_end:
    lda #0
    sta trk3_active
    lda #$10
    sta AUDC4
    jmp ch3_skip

ch3_raw_no_pitch:
    inc trk3_vector_offset
    beq ch3_raw_np_page
    jmp ch3_skip

ch3_raw_np_page:
    inc trk3_sample_ptr+1
    jmp ch3_raw_page_check
ch3_raw_p_page:
    inc trk3_sample_ptr+1
ch3_raw_page_check:
    lda trk3_sample_ptr+1
    cmp #$80
    bcs ch3_raw_bank_cross
    ldx ch3_banks_left          ; X test, preserves A=sample_ptr+1
    bne ch3_raw_page_ok
    cmp trk3_stream_end+1        ; A still = sample_ptr+1
    bcc ch3_raw_page_ok
    jmp ch3_end
ch3_raw_bank_cross:
    lda ch3_banks_left
    bne *+5
    jmp ch3_end
    lda #$40
    sta trk3_sample_ptr+1
    inc ch3_bank_seq_idx
    ldx ch3_bank_seq_idx
    lda SAMPLE_BANK_SEQ,x
    sta ch3_bank
    sta PORTB
    dec ch3_banks_left
ch3_raw_page_ok:
    jmp ch3_skip

ch3_raw_pitch:
    clc
    lda trk3_pitch_frac
    adc trk3_pitch_step
    sta trk3_pitch_frac
    lda trk3_vector_offset
    adc trk3_pitch_step+1
    sta trk3_vector_offset
    bcs ch3_raw_p_page

ch3_skip:

    ; =========================================================================
    ; EXIT - Restore PORTB to main RAM
    ; =========================================================================
    lda #PORTB_MAIN
    sta PORTB

    ldy irq_save_y
    ldx irq_save_x
    lda irq_save_a
    rti
