; ==========================================================================
; TRACKER IRQ HANDLER - BANKED (4-channel, Mixed RAW/VQ, Extended Memory)
; ==========================================================================
; Macro-based: CHANNEL_IRQ macro generates identical code per channel.
; Single point of maintenance — ~200 lines of macro replaces ~800 lines.
;
; Bank window exit detection ($4000-$7FFF → $8000+) uses the N flag
; instead of explicit CMP #$80:
;   - After INC ptr+1: N flag set if result >= $80 → BPL skips bank cross
;   - After LDA ptr+1: N flag set by LDA → BMI branches to bank cross
; Saves 2-4 bytes and 2-5 cycles per check (12 checks × 4 channels).
;
; RAW pitch hot path: falls through to chN_skip (zero branch overhead).
;
; SMC per channel (patched by process_row.asm):
;   chN_bank     - PORTB value for sample bank
;   chN_tick_jmp - JMP target: one of 4 mode+pitch handlers
;
; All handler labels (chN_vq_pitch, chN_raw_no_pitch, etc.) are made
; globally visible using ".def" for SMC patching by process_row.asm.
; (MADS macro labels are local by default — .def overrides this.)
; ==========================================================================

.ifndef USE_BANKING
    .error "tracker_irq_banked.asm requires USE_BANKING to be defined"
.endif

; Default MIN_VECTOR for all-RAW builds (converter omits it when algo=raw).
; Must be defined BEFORE any usage below (CODEBOOK_SIZE fallback, VECTOR_MASK).
.ifndef MIN_VECTOR
    MIN_VECTOR = 8
.endif

; Per-bank codebook: VQ lookup tables point into codebook at $4000.
; BANK_CODEBOOK_BYTES comes from VQ_CFG.asm (set by build pipeline):
;   - Non-zero when VQ instruments present (256 * vec_size)
;   - Zero when no VQ instruments exist
.ifdef BANK_CODEBOOK_BYTES
    CODEBOOK_SIZE = BANK_CODEBOOK_BYTES
.else
    CODEBOOK_SIZE = 256 * MIN_VECTOR
.endif
; BANK_DATA_HI: legacy constant, retained for reference.
; Bank-crossing code uses per-channel ch:1_data_hi instead (set from
; SAMPLE_DATA_HI table in BANK_CFG.asm at note trigger time).
BANK_DATA_HI = >($4000 + CODEBOOK_SIZE)

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

; ==========================================================================
; CHANNEL_IRQ — Per-channel IRQ handler macro
; ==========================================================================
; :1 = channel number (0-3)     Label/variable names: ch:1_xxx, trk:1_xxx
; :2 = AUDC register            AUDC1 through AUDC4
;
; IMPORTANT: MADS makes all labels inside .macro/.endm local to each
; invocation.  Labels that must be visible to process_row.asm (for SMC
; patching) use ".def name = *" to force global scope.  Internal-only
; labels (ch:1_active, ch:1_skip, etc.) remain local.
; ==========================================================================
.macro CHANNEL_IRQ

    ; --- Active check ---
    lda trk:1_active
    bne ch:1_active
    jmp ch:1_skip
ch:1_active:

    ; --- Bank switch + Output sample ---
.def ch:1_bank = *+1              ; .def → global (SMC target for process_row)
    ldx #PORTB_MAIN              ; SMC: patched to instrument's PORTB
    stx PORTB

    ldy trk:1_vector_offset
.if VOLUME_CONTROL = 1
    lda (trk:1_sample_ptr),y
    and #$0F
    ora trk:1_vol_shift
    tax
    lda VOLUME_SCALE,x
    sta :2
.else
    lda (trk:1_sample_ptr),y
    sta :2
.endif

    ; --- Unified mode+pitch dispatch ---
.def ch:1_tick_jmp = *+1          ; .def → global (SMC target for process_row)
    jmp ch:1_raw_pitch           ; SMC: one of 4 handler targets

    ; =================================================================
    ; VQ NO-PITCH
    ; =================================================================
.def ch:1_vq_no_pitch = *         ; .def → global (jump target for process_row)
    inc trk:1_vector_offset
    lda trk:1_vector_offset
    cmp #MIN_VECTOR
    bcs ch:1_vq_boundary
    jmp ch:1_skip

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
    beq ch:1_vq_pitch_done
    clc
    lda trk:1_vector_offset
    adc trk:1_pitch_int
    sta trk:1_vector_offset
    lda #0
    sta trk:1_pitch_int
    lda trk:1_vector_offset
    cmp #MIN_VECTOR
    bcc ch:1_vq_pitch_done
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
    bcc ch:1_vq_p_nc
    ; Stream ptr high byte page cross — check bank window exit
    inc trk:1_stream_ptr+1
    bpl ch:1_vq_p_nc             ; N clear = hi < $80 = still in bank window
    ; Exited bank window ($80+) — switch to next bank or end
    lda ch:1_banks_left
    bne @+
    jmp ch:1_end
@   lda ch:1_data_hi
    sta trk:1_stream_ptr+1
    inc ch:1_bank_seq_idx
    ldy ch:1_bank_seq_idx
    lda SAMPLE_BANK_SEQ,y
    sta ch:1_bank
    sta PORTB
    dec ch:1_banks_left
ch:1_vq_p_nc:
    txa
    and #VECTOR_MASK
    sta trk:1_vector_offset
    jmp ch:1_check_end
ch:1_vq_pitch_done:
    jmp ch:1_skip

    ; =================================================================
    ; VQ BOUNDARY (no-pitch path crossed MIN_VECTOR)
    ; =================================================================
ch:1_vq_boundary:
    lda #0
    sta trk:1_vector_offset
    inc trk:1_stream_ptr
    bne ch:1_check_end
    ; Low byte wrapped to 0 — increment high, check bank exit
    inc trk:1_stream_ptr+1
    bpl ch:1_check_end           ; N clear = still in bank window
    ; Exited bank window
    lda ch:1_banks_left
    bne @+
    jmp ch:1_end
@   lda ch:1_data_hi
    sta trk:1_stream_ptr+1
    inc ch:1_bank_seq_idx
    ldx ch:1_bank_seq_idx
    lda SAMPLE_BANK_SEQ,x
    sta ch:1_bank
    sta PORTB
    dec ch:1_banks_left
    jmp ch:1_load_vector

    ; =================================================================
    ; CHECK END + LOAD VECTOR
    ; =================================================================
ch:1_check_end:
    lda ch:1_banks_left
    bne ch:1_load_vector
    lda trk:1_stream_ptr+1
    cmp trk:1_stream_end+1
    bcc ch:1_load_vector
    bne ch:1_end
    lda trk:1_stream_ptr
    cmp trk:1_stream_end
    bcs ch:1_end

ch:1_load_vector:
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
    jmp ch:1_skip

    ; =================================================================
    ; RAW NO-PITCH
    ; =================================================================
.def ch:1_raw_no_pitch = *        ; .def → global (jump target for process_row)
    inc trk:1_vector_offset       ; 5
    beq ch:1_raw_np_page          ; 2 (not taken 255/256)
    jmp ch:1_skip                 ; 3

    ; =================================================================
    ; RAW PAGE CROSS (shared by no-pitch and pitch)
    ; =================================================================
ch:1_raw_np_page:
    inc trk:1_sample_ptr+1
    jmp ch:1_raw_page_check
ch:1_raw_p_page:
    inc trk:1_sample_ptr+1
ch:1_raw_page_check:
    ; Need A = sample_ptr+1 for end-of-stream check below.
    ; LDA sets N flag → BMI branches if >= $80 (exited bank window).
    lda trk:1_sample_ptr+1
    bmi ch:1_raw_bank_cross       ; bit 7 set = past $7FFF
    ldx ch:1_banks_left           ; preserves A
    bne ch:1_raw_page_ok
    cmp trk:1_stream_end+1        ; A = sample_ptr+1
    bcc ch:1_raw_page_ok          ; hi < end_hi → still playing
    bne ch:1_end                  ; hi > end_hi → past end
    ; hi == end_hi: check low byte (vector_offset vs stream_end lo)
    lda trk:1_vector_offset
    cmp trk:1_stream_end
    bcc ch:1_raw_page_ok          ; offset < end_lo → still playing
    jmp ch:1_end                  ; offset >= end_lo → end
ch:1_raw_bank_cross:
    lda ch:1_banks_left
    bne @+
    jmp ch:1_end
@   lda ch:1_data_hi
    sta trk:1_sample_ptr+1
    inc ch:1_bank_seq_idx
    ldx ch:1_bank_seq_idx
    lda SAMPLE_BANK_SEQ,x
    sta ch:1_bank
    sta PORTB
    dec ch:1_banks_left
ch:1_raw_page_ok:
    jmp ch:1_skip

    ; =================================================================
    ; RAW PITCH (HOT PATH — falls through to chN_skip!)
    ; =================================================================
.def ch:1_raw_pitch = *           ; .def → global (jump target for process_row)
    clc                          ; 2
    lda trk:1_pitch_frac         ; 3
    adc trk:1_pitch_step         ; 3
    sta trk:1_pitch_frac         ; 3
    lda trk:1_vector_offset      ; 3
    adc trk:1_pitch_step+1       ; 3 (+carry from frac)
    sta trk:1_vector_offset      ; 3
    bcs ch:1_raw_p_page          ; 2 (not taken → fall through!)

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

    ; === Channel 0 — AUDC1 ================================================
    CHANNEL_IRQ 0, AUDC1

    ; === Channel 1 — AUDC2 ================================================
    CHANNEL_IRQ 1, AUDC2

    ; === Channel 2 — AUDC3 ================================================
    CHANNEL_IRQ 2, AUDC3

    ; === Channel 3 — AUDC4 ================================================
    CHANNEL_IRQ 3, AUDC4

    ; === Exit — restore PORTB to main RAM ==================================
    lda #PORTB_MAIN
    sta PORTB

    ldy irq_save_y
    ldx irq_save_x
    lda irq_save_a
    rti
