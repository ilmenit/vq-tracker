; ==========================================================================
; TRACKER IRQ HANDLER - SIZE OPTIMIZED (4-channel, Nibble-packed VQ only)
; ==========================================================================
; Timer-driven IRQ for nibble-packed VQ samples with pitch control.
; No RAW mode support. ch:1_raw_xxx aliases provided for process_row.asm.
;
; Cycle counts per channel (VOLUME_CONTROL=0):
;   VQ no-pitch, no boundary: ~35 cycles
;   VQ pitch, no advance:     ~28 cycles
;   Inactive channel:          5 cycles
; ==========================================================================

; Default MIN_VECTOR for all-RAW builds (converter omits it when algo=raw)
.ifndef MIN_VECTOR
    MIN_VECTOR = 8
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

; ==========================================================================
; CHANNEL_IRQ_SIZE — Per-channel nibble-packed VQ handler
; ==========================================================================
; :1 = channel (0-3)
; :2 = AUDC register (AUDC1..AUDC4)
;
; IMPORTANT: Labels visible to process_row.asm use ".def name = *" to
; force global scope (MADS macro labels are local by default).
; ==========================================================================
.macro CHANNEL_IRQ_SIZE

    lda trk:1_active
    beq ch:1_skip

    ; --- Unpack nibble from sample vector ---
    lda trk:1_vector_offset
    lsr
    tay
    lda (trk:1_sample_ptr),y
    tax

    lda trk:1_vector_offset
    and #$01
    bne @high_:1

    ; Low nibble
.if VOLUME_CONTROL = 1
    lda LUT_NIBBLE_LO,x
    and #$0F
    ora trk:1_vol_shift
    tax
    lda VOLUME_SCALE,x
    sta :2
.else
    lda LUT_NIBBLE_LO,x
    sta :2
.endif
    jmp @advance_:1

@high_:1:
    ; High nibble
.if VOLUME_CONTROL = 1
    lda LUT_NIBBLE_HI,x
    and #$0F
    ora trk:1_vol_shift
    tax
    lda VOLUME_SCALE,x
    sta :2
.else
    lda LUT_NIBBLE_HI,x
    sta :2
.endif

@advance_:1:
    ; --- Mode+pitch dispatch (SMC) ---
.def ch:1_tick_jmp = *+1          ; .def → global (SMC target for process_row)
    jmp ch:1_vq_no_pitch

    ; =================================================================
    ; VQ NO-PITCH
    ; =================================================================
.def ch:1_vq_no_pitch = *         ; .def → global (jump target for process_row)
    inc trk:1_vector_offset
    lda trk:1_vector_offset
    cmp #MIN_VECTOR
    bcc ch:1_skip

    lda #0
    sta trk:1_vector_offset
    inc trk:1_stream_ptr
    bne @check_end_:1
    inc trk:1_stream_ptr+1

@check_end_:1:
    lda trk:1_stream_ptr+1
    cmp trk:1_stream_end+1
    bcc @load_vec_:1
    bne ch:1_end
    lda trk:1_stream_ptr
    cmp trk:1_stream_end
    bcs ch:1_end

@load_vec_:1:
    ldy #0
    lda (trk:1_stream_ptr),y
    tay
    lda VQ_LO,y
    sta trk:1_sample_ptr
    lda VQ_HI,y
    sta trk:1_sample_ptr+1
    jmp ch:1_skip

ch:1_end:
    lda #0
    sta trk:1_active
    lda #$10
    sta :2
    bpl ch:1_skip              ; unconditional: $10 has N=0

    ; =================================================================
    ; VQ PITCH
    ; =================================================================
.def ch:1_vq_pitch = *            ; .def → global (jump target for process_row)
    clc
    lda trk:1_pitch_frac
    adc trk:1_pitch_step
    sta trk:1_pitch_frac
    lda trk:1_pitch_int
    adc trk:1_pitch_step+1
    sta trk:1_pitch_int
    beq ch:1_skip               ; no whole-sample advance this tick

    clc
    lda trk:1_vector_offset
    adc trk:1_pitch_int
    sta trk:1_vector_offset
    lda #0
    sta trk:1_pitch_int

    lda trk:1_vector_offset
    cmp #MIN_VECTOR
    bcc ch:1_skip

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
    adc trk:1_stream_ptr
    sta trk:1_stream_ptr
    bcc @p_nc_:1
    inc trk:1_stream_ptr+1
@p_nc_:1:
    txa
    and #VECTOR_MASK
    sta trk:1_vector_offset
    jmp @check_end_:1

ch:1_skip:
.endm

; ==========================================================================
; IRQ ENTRY
; ==========================================================================
Tracker_IRQ:
    sta irq_save_a
    stx irq_save_x
    sty irq_save_y

    lda #0
    sta IRQEN
    lda #IRQ_MASK
    sta IRQEN

    CHANNEL_IRQ_SIZE 0, AUDC1
    CHANNEL_IRQ_SIZE 1, AUDC2
    CHANNEL_IRQ_SIZE 2, AUDC3
    CHANNEL_IRQ_SIZE 3, AUDC4

    ; === Exit ===
    lda irq_save_a
    ldx irq_save_x
    ldy irq_save_y
    rti

; RAW label aliases (size handler is VQ-only; needed for process_row.asm)
ch0_raw_no_pitch = ch0_vq_no_pitch
ch0_raw_pitch    = ch0_vq_pitch
ch1_raw_no_pitch = ch1_vq_no_pitch
ch1_raw_pitch    = ch1_vq_pitch
ch2_raw_no_pitch = ch2_vq_no_pitch
ch2_raw_pitch    = ch2_vq_pitch
ch3_raw_no_pitch = ch3_vq_no_pitch
ch3_raw_pitch    = ch3_vq_pitch
