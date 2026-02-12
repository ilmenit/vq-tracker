; ==========================================================================
; TRACKER IRQ HANDLER - SPEED OPTIMIZED (4-channel, Mixed RAW/VQ)
; ==========================================================================
; Timer-driven interrupt handler for playing VQ-compressed AND RAW
; (uncompressed) samples with pitch control on 4 independent POKEY channels.
;
; Data format: VQ_BLOB and RAW_SAMPLES store raw volume 0-15 (no AUDC mask).
; The VOLUME_CONTROL path combines with note volume via ORA + VOLUME_SCALE.
; The non-volume path adds ORA #$10 for AUDC distortion C mode.
;
; RAW/VQ mode is selected per-channel at note-start time (process_row.asm)
; via self-modifying code (SMC). Zero overhead for mode detection at IRQ rate.
;
; SMC locations per channel (written by process_row.asm under SEI):
;   chN_boundary_cmp  — CMP operand: MIN_VECTOR (VQ) or $00 (RAW)
;   chN_boundary_br   — Branch opcode: BCC/$90 (VQ) or BNE/$D0 (RAW)
;   chN_boundary_jmp  — JMP target: chN_vq_boundary or chN_raw_boundary
;   chN_pitch_jmp     — JMP target: chN_vq_pitch_chk or chN_raw_pitch_chk
;
; Layout: RAW handlers placed AFTER chN_skip so the common-path BCC/BNE
; branch stays short (within 127 bytes). RAW handlers are only reachable
; via SMC JMP targets, never by fall-through in VQ mode.
;
; Cycle counts (common non-boundary path per channel):
;   Active, no boundary, vol: ~30 cycles
;   Active, no boundary, no vol: ~14 cycles
;   Inactive channel: 7 cycles
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

; SMC opcodes (defined in song_player.asm; guarded here for standalone use)
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
    
    ; --- Output sample (identical for VQ and RAW) ---
    ldy trk0_vector_offset
.if VOLUME_CONTROL = 1
    lda (trk0_sample_ptr),y
    ora trk0_vol_shift
    tax
    lda VOLUME_SCALE,x
    sta AUDC1
.else
    lda (trk0_sample_ptr),y
    ora #$10
    sta AUDC1
.endif
    
    ; --- Pitch dispatch (SMC: BMI=has pitch, BPL=no pitch) ---
ch0_dispatch = *
    bmi ch0_pitch

    ; --- No-pitch: advance offset, check boundary ---
    inc trk0_vector_offset
    lda trk0_vector_offset
ch0_boundary_cmp = *+1
    cmp #MIN_VECTOR             ; SMC: MIN_VECTOR (VQ) or $00 (RAW)
ch0_boundary_br = *
    bcs ch0_bnd_dispatch      ; SMC: BCS/$B0 (VQ) or BEQ/$F0 (RAW)
    jmp ch0_skip              ; no boundary: far jump to skip
    
    ; --- Boundary reached: dispatch via SMC JMP ---
ch0_bnd_dispatch:
ch0_boundary_jmp = *+1
    jmp ch0_vq_boundary       ; SMC target: ch0_vq_boundary or ch0_raw_boundary

    ; --- VQ boundary: advance index stream, load next codebook vector ---
ch0_vq_boundary:
    lda #0
    sta trk0_vector_offset
    inc trk0_stream_ptr
    bne ch0_check_end
    inc trk0_stream_ptr+1

ch0_check_end:
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

    ; --- Pitch path ---
ch0_pitch:
    clc
    lda trk0_pitch_frac
    adc trk0_pitch_step
    sta trk0_pitch_frac
    lda trk0_pitch_int
    adc trk0_pitch_step+1
    sta trk0_pitch_int
    
    beq ch0_skip              ; no integer advance this tick
    
    clc
    lda trk0_vector_offset
    adc trk0_pitch_int
    sta trk0_vector_offset     ; carry preserved for RAW pitch check
    
    lda #0
    sta trk0_pitch_int         ; does NOT affect carry
    
    ; --- Dispatch to VQ or RAW pitch boundary check ---
ch0_pitch_jmp = *+1
    jmp ch0_vq_pitch_chk       ; SMC target: ch0_vq_pitch_chk or ch0_raw_pitch_chk

ch0_vq_pitch_chk:
    lda trk0_vector_offset
    cmp #MIN_VECTOR
    bcc ch0_skip
    
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
    bcc ch0_p_nc
    inc trk0_stream_ptr+1
ch0_p_nc:
    txa
    and #VECTOR_MASK
    sta trk0_vector_offset
    jmp ch0_check_end

ch0_skip:

    ; =========================================================================
    ; CHANNEL 1 - AUDC2
    ; =========================================================================
    lda trk1_active
    bne ch1_active
    jmp ch1_skip
ch1_active:
    
    ; --- Output sample (identical for VQ and RAW) ---
    ldy trk1_vector_offset
.if VOLUME_CONTROL = 1
    lda (trk1_sample_ptr),y
    ora trk1_vol_shift
    tax
    lda VOLUME_SCALE,x
    sta AUDC2
.else
    lda (trk1_sample_ptr),y
    ora #$10
    sta AUDC2
.endif
    
    ; --- Pitch dispatch (SMC: BMI=has pitch, BPL=no pitch) ---
ch1_dispatch = *
    bmi ch1_pitch

    ; --- No-pitch: advance offset, check boundary ---
    inc trk1_vector_offset
    lda trk1_vector_offset
ch1_boundary_cmp = *+1
    cmp #MIN_VECTOR             ; SMC: MIN_VECTOR (VQ) or $00 (RAW)
ch1_boundary_br = *
    bcs ch1_bnd_dispatch      ; SMC: BCS/$B0 (VQ) or BEQ/$F0 (RAW)
    jmp ch1_skip              ; no boundary: far jump to skip
    
    ; --- Boundary reached: dispatch via SMC JMP ---
ch1_bnd_dispatch:
ch1_boundary_jmp = *+1
    jmp ch1_vq_boundary       ; SMC target: ch1_vq_boundary or ch1_raw_boundary

    ; --- VQ boundary: advance index stream, load next codebook vector ---
ch1_vq_boundary:
    lda #0
    sta trk1_vector_offset
    inc trk1_stream_ptr
    bne ch1_check_end
    inc trk1_stream_ptr+1

ch1_check_end:
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

    ; --- Pitch path ---
ch1_pitch:
    clc
    lda trk1_pitch_frac
    adc trk1_pitch_step
    sta trk1_pitch_frac
    lda trk1_pitch_int
    adc trk1_pitch_step+1
    sta trk1_pitch_int
    
    beq ch1_skip              ; no integer advance this tick
    
    clc
    lda trk1_vector_offset
    adc trk1_pitch_int
    sta trk1_vector_offset     ; carry preserved for RAW pitch check
    
    lda #0
    sta trk1_pitch_int         ; does NOT affect carry
    
    ; --- Dispatch to VQ or RAW pitch boundary check ---
ch1_pitch_jmp = *+1
    jmp ch1_vq_pitch_chk       ; SMC target: ch1_vq_pitch_chk or ch1_raw_pitch_chk

ch1_vq_pitch_chk:
    lda trk1_vector_offset
    cmp #MIN_VECTOR
    bcc ch1_skip
    
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
    bcc ch1_p_nc
    inc trk1_stream_ptr+1
ch1_p_nc:
    txa
    and #VECTOR_MASK
    sta trk1_vector_offset
    jmp ch1_check_end

ch1_skip:

    ; =========================================================================
    ; CHANNEL 2 - AUDC3
    ; =========================================================================
    lda trk2_active
    bne ch2_active
    jmp ch2_skip
ch2_active:
    
    ; --- Output sample (identical for VQ and RAW) ---
    ldy trk2_vector_offset
.if VOLUME_CONTROL = 1
    lda (trk2_sample_ptr),y
    ora trk2_vol_shift
    tax
    lda VOLUME_SCALE,x
    sta AUDC3
.else
    lda (trk2_sample_ptr),y
    ora #$10
    sta AUDC3
.endif
    
    ; --- Pitch dispatch (SMC: BMI=has pitch, BPL=no pitch) ---
ch2_dispatch = *
    bmi ch2_pitch

    ; --- No-pitch: advance offset, check boundary ---
    inc trk2_vector_offset
    lda trk2_vector_offset
ch2_boundary_cmp = *+1
    cmp #MIN_VECTOR             ; SMC: MIN_VECTOR (VQ) or $00 (RAW)
ch2_boundary_br = *
    bcs ch2_bnd_dispatch      ; SMC: BCS/$B0 (VQ) or BEQ/$F0 (RAW)
    jmp ch2_skip              ; no boundary: far jump to skip
    
    ; --- Boundary reached: dispatch via SMC JMP ---
ch2_bnd_dispatch:
ch2_boundary_jmp = *+1
    jmp ch2_vq_boundary       ; SMC target: ch2_vq_boundary or ch2_raw_boundary

    ; --- VQ boundary: advance index stream, load next codebook vector ---
ch2_vq_boundary:
    lda #0
    sta trk2_vector_offset
    inc trk2_stream_ptr
    bne ch2_check_end
    inc trk2_stream_ptr+1

ch2_check_end:
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

    ; --- Pitch path ---
ch2_pitch:
    clc
    lda trk2_pitch_frac
    adc trk2_pitch_step
    sta trk2_pitch_frac
    lda trk2_pitch_int
    adc trk2_pitch_step+1
    sta trk2_pitch_int
    
    beq ch2_skip              ; no integer advance this tick
    
    clc
    lda trk2_vector_offset
    adc trk2_pitch_int
    sta trk2_vector_offset     ; carry preserved for RAW pitch check
    
    lda #0
    sta trk2_pitch_int         ; does NOT affect carry
    
    ; --- Dispatch to VQ or RAW pitch boundary check ---
ch2_pitch_jmp = *+1
    jmp ch2_vq_pitch_chk       ; SMC target: ch2_vq_pitch_chk or ch2_raw_pitch_chk

ch2_vq_pitch_chk:
    lda trk2_vector_offset
    cmp #MIN_VECTOR
    bcc ch2_skip
    
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
    bcc ch2_p_nc
    inc trk2_stream_ptr+1
ch2_p_nc:
    txa
    and #VECTOR_MASK
    sta trk2_vector_offset
    jmp ch2_check_end

ch2_skip:

    ; =========================================================================
    ; CHANNEL 3 - AUDC4
    ; =========================================================================
    lda trk3_active
    bne ch3_active
    jmp ch3_skip
ch3_active:
    
    ; --- Output sample (identical for VQ and RAW) ---
    ldy trk3_vector_offset
.if VOLUME_CONTROL = 1
    lda (trk3_sample_ptr),y
    ora trk3_vol_shift
    tax
    lda VOLUME_SCALE,x
    sta AUDC4
.else
    lda (trk3_sample_ptr),y
    ora #$10
    sta AUDC4
.endif
    
    ; --- Pitch dispatch (SMC: BMI=has pitch, BPL=no pitch) ---
ch3_dispatch = *
    bmi ch3_pitch

    ; --- No-pitch: advance offset, check boundary ---
    inc trk3_vector_offset
    lda trk3_vector_offset
ch3_boundary_cmp = *+1
    cmp #MIN_VECTOR             ; SMC: MIN_VECTOR (VQ) or $00 (RAW)
ch3_boundary_br = *
    bcs ch3_bnd_dispatch      ; SMC: BCS/$B0 (VQ) or BEQ/$F0 (RAW)
    jmp ch3_skip              ; no boundary: far jump to skip
    
    ; --- Boundary reached: dispatch via SMC JMP ---
ch3_bnd_dispatch:
ch3_boundary_jmp = *+1
    jmp ch3_vq_boundary       ; SMC target: ch3_vq_boundary or ch3_raw_boundary

    ; --- VQ boundary: advance index stream, load next codebook vector ---
ch3_vq_boundary:
    lda #0
    sta trk3_vector_offset
    inc trk3_stream_ptr
    bne ch3_check_end
    inc trk3_stream_ptr+1

ch3_check_end:
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

    ; --- Pitch path ---
ch3_pitch:
    clc
    lda trk3_pitch_frac
    adc trk3_pitch_step
    sta trk3_pitch_frac
    lda trk3_pitch_int
    adc trk3_pitch_step+1
    sta trk3_pitch_int
    
    beq ch3_skip              ; no integer advance this tick
    
    clc
    lda trk3_vector_offset
    adc trk3_pitch_int
    sta trk3_vector_offset     ; carry preserved for RAW pitch check
    
    lda #0
    sta trk3_pitch_int         ; does NOT affect carry
    
    ; --- Dispatch to VQ or RAW pitch boundary check ---
ch3_pitch_jmp = *+1
    jmp ch3_vq_pitch_chk       ; SMC target: ch3_vq_pitch_chk or ch3_raw_pitch_chk

ch3_vq_pitch_chk:
    lda trk3_vector_offset
    cmp #MIN_VECTOR
    bcc ch3_skip
    
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
    bcc ch3_p_nc
    inc trk3_stream_ptr+1
ch3_p_nc:
    txa
    and #VECTOR_MASK
    sta trk3_vector_offset
    jmp ch3_check_end

ch3_skip:

    ; =========================================================================
    ; EXIT
    ; =========================================================================
    ldy irq_save_y
    ldx irq_save_x
    lda irq_save_a
    rti

    ; =========================================================================
    ; RAW HANDLERS - Separate section (reached only via SMC JMP targets)
    ; =========================================================================
    ; Placed after RTI so chN_skip labels fall through to the next channel
    ; (or IRQ exit for ch3) with zero overhead on the common path.
    ;
    ; Each handler exits via JMP to the channel's _skip or _end label.
    ; =========================================================================

    ; --- Channel 0 RAW ---
ch0_raw_boundary:
    ; vector_offset wrapped $FF→$00 from inc
    inc trk0_sample_ptr+1
    lda trk0_sample_ptr+1
    cmp trk0_stream_end+1
    bcc ch0_raw_done
    jmp ch0_end
ch0_raw_done:
    jmp ch0_skip

ch0_raw_pitch_chk:
    bcc ch0_raw_done           ; carry from adc: clear=no page cross
    inc trk0_sample_ptr+1
    lda trk0_sample_ptr+1
    cmp trk0_stream_end+1
    bcc ch0_raw_done
    jmp ch0_end

    ; --- Channel 1 RAW ---
ch1_raw_boundary:
    inc trk1_sample_ptr+1
    lda trk1_sample_ptr+1
    cmp trk1_stream_end+1
    bcc ch1_raw_done
    jmp ch1_end
ch1_raw_done:
    jmp ch1_skip

ch1_raw_pitch_chk:
    bcc ch1_raw_done
    inc trk1_sample_ptr+1
    lda trk1_sample_ptr+1
    cmp trk1_stream_end+1
    bcc ch1_raw_done
    jmp ch1_end

    ; --- Channel 2 RAW ---
ch2_raw_boundary:
    inc trk2_sample_ptr+1
    lda trk2_sample_ptr+1
    cmp trk2_stream_end+1
    bcc ch2_raw_done
    jmp ch2_end
ch2_raw_done:
    jmp ch2_skip

ch2_raw_pitch_chk:
    bcc ch2_raw_done
    inc trk2_sample_ptr+1
    lda trk2_sample_ptr+1
    cmp trk2_stream_end+1
    bcc ch2_raw_done
    jmp ch2_end

    ; --- Channel 3 RAW ---
ch3_raw_boundary:
    inc trk3_sample_ptr+1
    lda trk3_sample_ptr+1
    cmp trk3_stream_end+1
    bcc ch3_raw_done
    jmp ch3_end
ch3_raw_done:
    jmp ch3_skip

ch3_raw_pitch_chk:
    bcc ch3_raw_done
    inc trk3_sample_ptr+1
    lda trk3_sample_ptr+1
    cmp trk3_stream_end+1
    bcc ch3_raw_done
    jmp ch3_end
