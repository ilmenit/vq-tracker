; ==========================================================================
; PROCESS_ROW.ASM - Row Processing (4-channel, Mixed RAW/VQ)
; ==========================================================================
; Two-Phase Trigger Architecture for all 4 POKEY channels.
; Entry: JMP from main_loop when seq_tick reaches seq_speed
; Exit:  JMP back to ml_after_row
;
; Phase 1 (PREPARE): IRQ enabled. Lookup pitch, sample pointers, and
;   first codebook vector (VQ) or raw start address (RAW).
; Phase 2 (COMMIT): IRQ disabled (SEI). Copy prepared values to
;   IRQ-rate variables + write SMC for VQ/RAW boundary dispatch.
; ==========================================================================

    ; =========================================================================
    ; Clear trigger flags for all channels
    ; =========================================================================
    lda #0
    sta evt_trigger
    sta evt_trigger+1
    sta evt_trigger+2
    sta evt_trigger+3
    
    ; =========================================================================
    ; EVENT DISPATCH
    ; =========================================================================
    
    ; --- Channel 0 ---
    lda seq_evt_row
    cmp seq_local_row
    bne @pr_no_ch0
    ldx #0
    jsr parse_event
    lda #$FF
    sta evt_trigger
@pr_no_ch0:

    ; --- Channel 1 ---
    lda seq_evt_row+1
    cmp seq_local_row+1
    bne @pr_no_ch1
    ldx #1
    jsr parse_event
    lda #$FF
    sta evt_trigger+1
@pr_no_ch1:

    ; --- Channel 2 ---
    lda seq_evt_row+2
    cmp seq_local_row+2
    bne @pr_no_ch2
    ldx #2
    jsr parse_event
    lda #$FF
    sta evt_trigger+2
@pr_no_ch2:

    ; --- Channel 3 ---
    lda seq_evt_row+3
    cmp seq_local_row+3
    bne @pr_no_ch3
    ldx #3
    jsr parse_event
    lda #$FF
    sta evt_trigger+3
@pr_no_ch3:

    ; =========================================================================
    ; PHASE 1: PREPARE (IRQ enabled)
    ; =========================================================================
    
    ; --- Prepare Channel 0 ---
    lda evt_trigger
    beq @prep_done_0
    lda evt_note
    beq @prep_done_0
    
    sec
    sbc #1
    tax
    lda NOTE_PITCH_LO,x
    sta prep0_pitch_lo
    lda NOTE_PITCH_HI,x
    sta prep0_pitch_hi
    
    lda evt_inst
    and #$7F
    tax
    lda SAMPLE_START_LO,x
    sta prep0_stream_lo
    lda SAMPLE_START_HI,x
    sta prep0_stream_hi
    lda SAMPLE_END_LO,x
    sta prep0_end_lo
    lda SAMPLE_END_HI,x
    sta prep0_end_hi
    
    lda SAMPLE_MODE,x           ; 0=VQ, non-zero=RAW
    sta prep0_mode
    bne @prep0_raw
    
    ; VQ: look up first codebook vector from index stream
    lda prep0_stream_lo
    sta trk_ptr
    lda prep0_stream_hi
    sta trk_ptr+1
    ldy #0
    lda (trk_ptr),y
    tay
    lda VQ_LO,y
    sta prep0_vq_lo
    lda VQ_HI,y
    sta prep0_vq_hi
    
    jmp @prep0_vol
    
@prep0_raw:
    ; RAW: sample_ptr = raw data start address directly
    lda prep0_stream_lo
    sta prep0_vq_lo
    lda prep0_stream_hi
    sta prep0_vq_hi
    
@prep0_vol:
.if VOLUME_CONTROL = 1
    lda evt_vol
    asl
    asl
    asl
    asl
    sta prep0_vol
.endif
@prep_done_0:

    ; --- Prepare Channel 1 ---
    lda evt_trigger+1
    beq @prep_done_1
    lda evt_note+1
    beq @prep_done_1
    
    sec
    sbc #1
    tax
    lda NOTE_PITCH_LO,x
    sta prep1_pitch_lo
    lda NOTE_PITCH_HI,x
    sta prep1_pitch_hi
    
    lda evt_inst+1
    and #$7F
    tax
    lda SAMPLE_START_LO,x
    sta prep1_stream_lo
    lda SAMPLE_START_HI,x
    sta prep1_stream_hi
    lda SAMPLE_END_LO,x
    sta prep1_end_lo
    lda SAMPLE_END_HI,x
    sta prep1_end_hi
    
    lda SAMPLE_MODE,x
    sta prep1_mode
    bne @prep1_raw
    
    lda prep1_stream_lo
    sta trk_ptr
    lda prep1_stream_hi
    sta trk_ptr+1
    ldy #0
    lda (trk_ptr),y
    tay
    lda VQ_LO,y
    sta prep1_vq_lo
    lda VQ_HI,y
    sta prep1_vq_hi
    
    jmp @prep1_vol
    
@prep1_raw:
    lda prep1_stream_lo
    sta prep1_vq_lo
    lda prep1_stream_hi
    sta prep1_vq_hi
    
@prep1_vol:
.if VOLUME_CONTROL = 1
    lda evt_vol+1
    asl
    asl
    asl
    asl
    sta prep1_vol
.endif
@prep_done_1:

    ; --- Prepare Channel 2 ---
    lda evt_trigger+2
    beq @prep_done_2
    lda evt_note+2
    beq @prep_done_2
    
    sec
    sbc #1
    tax
    lda NOTE_PITCH_LO,x
    sta prep2_pitch_lo
    lda NOTE_PITCH_HI,x
    sta prep2_pitch_hi
    
    lda evt_inst+2
    and #$7F
    tax
    lda SAMPLE_START_LO,x
    sta prep2_stream_lo
    lda SAMPLE_START_HI,x
    sta prep2_stream_hi
    lda SAMPLE_END_LO,x
    sta prep2_end_lo
    lda SAMPLE_END_HI,x
    sta prep2_end_hi
    
    lda SAMPLE_MODE,x
    sta prep2_mode
    bne @prep2_raw
    
    lda prep2_stream_lo
    sta trk_ptr
    lda prep2_stream_hi
    sta trk_ptr+1
    ldy #0
    lda (trk_ptr),y
    tay
    lda VQ_LO,y
    sta prep2_vq_lo
    lda VQ_HI,y
    sta prep2_vq_hi
    
    jmp @prep2_vol
    
@prep2_raw:
    lda prep2_stream_lo
    sta prep2_vq_lo
    lda prep2_stream_hi
    sta prep2_vq_hi
    
@prep2_vol:
.if VOLUME_CONTROL = 1
    lda evt_vol+2
    asl
    asl
    asl
    asl
    sta prep2_vol
.endif
@prep_done_2:

    ; --- Prepare Channel 3 ---
    lda evt_trigger+3
    beq @prep_done_3
    lda evt_note+3
    beq @prep_done_3
    
    sec
    sbc #1
    tax
    lda NOTE_PITCH_LO,x
    sta prep3_pitch_lo
    lda NOTE_PITCH_HI,x
    sta prep3_pitch_hi
    
    lda evt_inst+3
    and #$7F
    tax
    lda SAMPLE_START_LO,x
    sta prep3_stream_lo
    lda SAMPLE_START_HI,x
    sta prep3_stream_hi
    lda SAMPLE_END_LO,x
    sta prep3_end_lo
    lda SAMPLE_END_HI,x
    sta prep3_end_hi
    
    lda SAMPLE_MODE,x
    sta prep3_mode
    bne @prep3_raw
    
    lda prep3_stream_lo
    sta trk_ptr
    lda prep3_stream_hi
    sta trk_ptr+1
    ldy #0
    lda (trk_ptr),y
    tay
    lda VQ_LO,y
    sta prep3_vq_lo
    lda VQ_HI,y
    sta prep3_vq_hi
    
    jmp @prep3_vol
    
@prep3_raw:
    lda prep3_stream_lo
    sta prep3_vq_lo
    lda prep3_stream_hi
    sta prep3_vq_hi
    
@prep3_vol:
.if VOLUME_CONTROL = 1
    lda evt_vol+3
    asl
    asl
    asl
    asl
    sta prep3_vol
.endif
@prep_done_3:

    ; =========================================================================
    ; PHASE 2: COMMIT (IRQ disabled)
    ; =========================================================================
    
    sei                         ; *** IRQ DISABLED ***
    
    ; --- Commit Channel 0 ---
    lda evt_trigger
    bne @do_commit_0
    jmp @commit_done_0
@do_commit_0:
    lda evt_note
    bne @commit_note_0
    
    lda #0
    sta trk0_active
    lda #SILENCE
    sta AUDC1
    jmp @commit_done_0
    
@commit_note_0:
    lda #0
    sta trk0_active
    sta trk0_vector_offset
    
    ; Pitch setup
    lda prep0_pitch_hi
    cmp #$01
    bne @ch0_commit_pitch
    lda prep0_pitch_lo
    bne @ch0_commit_pitch
.if VOLUME_CONTROL = 1
    lda evt_vol
    cmp #15
    bne @ch0_commit_pitch
.endif
    
    lda #OPCODE_BMI             ; no-pitch dispatch
    sta ch0_dispatch
    jmp @ch0_commit_stream
    
@ch0_commit_pitch:
    lda #0
    sta trk0_pitch_frac
    sta trk0_pitch_int
    lda prep0_pitch_lo
    sta trk0_pitch_step
    lda prep0_pitch_hi
    sta trk0_pitch_step+1
    lda #OPCODE_BPL             ; pitch dispatch
    sta ch0_dispatch
    
@ch0_commit_stream:
    lda prep0_stream_lo
    sta trk0_stream_ptr
    lda prep0_stream_hi
    sta trk0_stream_ptr+1
    lda prep0_end_lo
    sta trk0_stream_end
    lda prep0_end_hi
    sta trk0_stream_end+1
    lda prep0_vq_lo
    sta trk0_sample_ptr
    lda prep0_vq_hi
    sta trk0_sample_ptr+1
.if VOLUME_CONTROL = 1
    lda prep0_vol
    sta trk0_vol_shift
.endif

    ; SMC setup: VQ or RAW boundary dispatch
    ; SMC: configure IRQ boundary dispatch for VQ or RAW mode
    lda prep0_mode
    bne @ch0_smc_raw
    
    ; VQ mode SMC
    lda #MIN_VECTOR
    sta ch0_boundary_cmp
    lda #OPCODE_BCS
    sta ch0_boundary_br
    lda #<ch0_vq_boundary
    sta ch0_boundary_jmp
    lda #>ch0_vq_boundary
    sta ch0_boundary_jmp+1
    lda #<ch0_vq_pitch_chk
    sta ch0_pitch_jmp
    lda #>ch0_vq_pitch_chk
    sta ch0_pitch_jmp+1
    jmp @ch0_activate
    
@ch0_smc_raw:
    ; RAW mode SMC
    lda #$00
    sta ch0_boundary_cmp
    lda #OPCODE_BEQ
    sta ch0_boundary_br
    lda #<ch0_raw_boundary
    sta ch0_boundary_jmp
    lda #>ch0_raw_boundary
    sta ch0_boundary_jmp+1
    lda #<ch0_raw_pitch_chk
    sta ch0_pitch_jmp
    lda #>ch0_raw_pitch_chk
    sta ch0_pitch_jmp+1
    
@ch0_activate:
    lda #$FF
    sta trk0_active
@commit_done_0:

    ; --- Commit Channel 1 ---
    lda evt_trigger+1
    bne @do_commit_1
    jmp @commit_done_1
@do_commit_1:
    lda evt_note+1
    bne @commit_note_1
    
    lda #0
    sta trk1_active
    lda #SILENCE
    sta AUDC2
    jmp @commit_done_1
    
@commit_note_1:
    lda #0
    sta trk1_active
    sta trk1_vector_offset
    
    lda prep1_pitch_hi
    cmp #$01
    bne @ch1_commit_pitch
    lda prep1_pitch_lo
    bne @ch1_commit_pitch
.if VOLUME_CONTROL = 1
    lda evt_vol+1
    cmp #15
    bne @ch1_commit_pitch
.endif
    
    lda #OPCODE_BMI
    sta ch1_dispatch
    jmp @ch1_commit_stream
    
@ch1_commit_pitch:
    lda #0
    sta trk1_pitch_frac
    sta trk1_pitch_int
    lda prep1_pitch_lo
    sta trk1_pitch_step
    lda prep1_pitch_hi
    sta trk1_pitch_step+1
    lda #OPCODE_BPL
    sta ch1_dispatch
    
@ch1_commit_stream:
    lda prep1_stream_lo
    sta trk1_stream_ptr
    lda prep1_stream_hi
    sta trk1_stream_ptr+1
    lda prep1_end_lo
    sta trk1_stream_end
    lda prep1_end_hi
    sta trk1_stream_end+1
    lda prep1_vq_lo
    sta trk1_sample_ptr
    lda prep1_vq_hi
    sta trk1_sample_ptr+1
.if VOLUME_CONTROL = 1
    lda prep1_vol
    sta trk1_vol_shift
.endif

    ; SMC: configure IRQ boundary dispatch for VQ or RAW mode
    lda prep1_mode
    bne @ch1_smc_raw
    
    lda #MIN_VECTOR
    sta ch1_boundary_cmp
    lda #OPCODE_BCS
    sta ch1_boundary_br
    lda #<ch1_vq_boundary
    sta ch1_boundary_jmp
    lda #>ch1_vq_boundary
    sta ch1_boundary_jmp+1
    lda #<ch1_vq_pitch_chk
    sta ch1_pitch_jmp
    lda #>ch1_vq_pitch_chk
    sta ch1_pitch_jmp+1
    jmp @ch1_activate
    
@ch1_smc_raw:
    lda #$00
    sta ch1_boundary_cmp
    lda #OPCODE_BEQ
    sta ch1_boundary_br
    lda #<ch1_raw_boundary
    sta ch1_boundary_jmp
    lda #>ch1_raw_boundary
    sta ch1_boundary_jmp+1
    lda #<ch1_raw_pitch_chk
    sta ch1_pitch_jmp
    lda #>ch1_raw_pitch_chk
    sta ch1_pitch_jmp+1
    
@ch1_activate:
    lda #$FF
    sta trk1_active
@commit_done_1:

    ; --- Commit Channel 2 ---
    lda evt_trigger+2
    bne @do_commit_2
    jmp @commit_done_2
@do_commit_2:
    lda evt_note+2
    bne @commit_note_2
    
    lda #0
    sta trk2_active
    lda #SILENCE
    sta AUDC3
    jmp @commit_done_2
    
@commit_note_2:
    lda #0
    sta trk2_active
    sta trk2_vector_offset
    
    lda prep2_pitch_hi
    cmp #$01
    bne @ch2_commit_pitch
    lda prep2_pitch_lo
    bne @ch2_commit_pitch
.if VOLUME_CONTROL = 1
    lda evt_vol+2
    cmp #15
    bne @ch2_commit_pitch
.endif
    
    lda #OPCODE_BMI
    sta ch2_dispatch
    jmp @ch2_commit_stream
    
@ch2_commit_pitch:
    lda #0
    sta trk2_pitch_frac
    sta trk2_pitch_int
    lda prep2_pitch_lo
    sta trk2_pitch_step
    lda prep2_pitch_hi
    sta trk2_pitch_step+1
    lda #OPCODE_BPL
    sta ch2_dispatch
    
@ch2_commit_stream:
    lda prep2_stream_lo
    sta trk2_stream_ptr
    lda prep2_stream_hi
    sta trk2_stream_ptr+1
    lda prep2_end_lo
    sta trk2_stream_end
    lda prep2_end_hi
    sta trk2_stream_end+1
    lda prep2_vq_lo
    sta trk2_sample_ptr
    lda prep2_vq_hi
    sta trk2_sample_ptr+1
.if VOLUME_CONTROL = 1
    lda prep2_vol
    sta trk2_vol_shift
.endif

    lda prep2_mode
    bne @ch2_smc_raw
    
    lda #MIN_VECTOR
    sta ch2_boundary_cmp
    lda #OPCODE_BCS
    sta ch2_boundary_br
    lda #<ch2_vq_boundary
    sta ch2_boundary_jmp
    lda #>ch2_vq_boundary
    sta ch2_boundary_jmp+1
    lda #<ch2_vq_pitch_chk
    sta ch2_pitch_jmp
    lda #>ch2_vq_pitch_chk
    sta ch2_pitch_jmp+1
    jmp @ch2_activate
    
@ch2_smc_raw:
    lda #$00
    sta ch2_boundary_cmp
    lda #OPCODE_BEQ
    sta ch2_boundary_br
    lda #<ch2_raw_boundary
    sta ch2_boundary_jmp
    lda #>ch2_raw_boundary
    sta ch2_boundary_jmp+1
    lda #<ch2_raw_pitch_chk
    sta ch2_pitch_jmp
    lda #>ch2_raw_pitch_chk
    sta ch2_pitch_jmp+1
    
@ch2_activate:
    lda #$FF
    sta trk2_active
@commit_done_2:

    ; --- Commit Channel 3 ---
    lda evt_trigger+3
    bne @do_commit_3
    jmp @commit_done_3
@do_commit_3:
    lda evt_note+3
    bne @commit_note_3
    
    lda #0
    sta trk3_active
    lda #SILENCE
    sta AUDC4
    jmp @commit_done_3
    
@commit_note_3:
    lda #0
    sta trk3_active
    sta trk3_vector_offset
    
    lda prep3_pitch_hi
    cmp #$01
    bne @ch3_commit_pitch
    lda prep3_pitch_lo
    bne @ch3_commit_pitch
.if VOLUME_CONTROL = 1
    lda evt_vol+3
    cmp #15
    bne @ch3_commit_pitch
.endif
    
    lda #OPCODE_BMI
    sta ch3_dispatch
    jmp @ch3_commit_stream
    
@ch3_commit_pitch:
    lda #0
    sta trk3_pitch_frac
    sta trk3_pitch_int
    lda prep3_pitch_lo
    sta trk3_pitch_step
    lda prep3_pitch_hi
    sta trk3_pitch_step+1
    lda #OPCODE_BPL
    sta ch3_dispatch
    
@ch3_commit_stream:
    lda prep3_stream_lo
    sta trk3_stream_ptr
    lda prep3_stream_hi
    sta trk3_stream_ptr+1
    lda prep3_end_lo
    sta trk3_stream_end
    lda prep3_end_hi
    sta trk3_stream_end+1
    lda prep3_vq_lo
    sta trk3_sample_ptr
    lda prep3_vq_hi
    sta trk3_sample_ptr+1
.if VOLUME_CONTROL = 1
    lda prep3_vol
    sta trk3_vol_shift
.endif

    lda prep3_mode
    bne @ch3_smc_raw
    
    lda #MIN_VECTOR
    sta ch3_boundary_cmp
    lda #OPCODE_BCS
    sta ch3_boundary_br
    lda #<ch3_vq_boundary
    sta ch3_boundary_jmp
    lda #>ch3_vq_boundary
    sta ch3_boundary_jmp+1
    lda #<ch3_vq_pitch_chk
    sta ch3_pitch_jmp
    lda #>ch3_vq_pitch_chk
    sta ch3_pitch_jmp+1
    jmp @ch3_activate
    
@ch3_smc_raw:
    lda #$00
    sta ch3_boundary_cmp
    lda #OPCODE_BEQ
    sta ch3_boundary_br
    lda #<ch3_raw_boundary
    sta ch3_boundary_jmp
    lda #>ch3_raw_boundary
    sta ch3_boundary_jmp+1
    lda #<ch3_raw_pitch_chk
    sta ch3_pitch_jmp
    lda #>ch3_raw_pitch_chk
    sta ch3_pitch_jmp+1
    
@ch3_activate:
    lda #$FF
    sta trk3_active
@commit_done_3:

    cli                         ; *** IRQ RE-ENABLED ***
    
    ; =========================================================================
    ; ADVANCE LOCAL ROWS - Per-channel pattern position (4 channels)
    ; =========================================================================
    ldx #3                      ; Start with channel 3
@pr_advance_local:
    inc seq_local_row,x
    lda seq_local_row,x
    cmp seq_ptn_len,x
    bcc @pr_no_wrap
    
    ; --- Pattern wrap ---
    lda #0
    sta seq_local_row,x
    
    lda seq_ptn_start_lo,x
    sta seq_evt_ptr_lo,x
    sta trk_ptr
    lda seq_ptn_start_hi,x
    sta seq_evt_ptr_hi,x
    sta trk_ptr+1
    
    stx parse_temp
    ldy #0
    lda (trk_ptr),y
    ldx parse_temp
    sta seq_evt_row,x
    
@pr_no_wrap:
    dex
    bpl @pr_advance_local       ; Loop while X >= 0
    
    ; =========================================================================
    ; ADVANCE GLOBAL ROW - Songline progression
    ; =========================================================================
    inc seq_row
    lda seq_row
    cmp seq_max_len
    bcc @pr_done
    
    ; --- Songline wrap ---
    lda #0
    sta seq_row
    
    inc seq_songline
    lda seq_songline
    cmp #SONG_LENGTH
    bcc @pr_load_new
    
    ; --- Song reached the end ---
.if KEY_CONTROL = 1
    ; Loop mode: wrap back to beginning
    lda #0
    sta seq_songline
.else
    ; Play-once mode: stop playback (main_loop will detect seq_playing=0)
    lda #0
    sta seq_songline
    sta seq_playing
    jmp @pr_done
.endif
    
@pr_load_new:
    jsr seq_load_songline
    
@pr_done:
    ; === END OF PROCESS_ROW ===
