; ==========================================================================
; PROCESS_ROW.ASM - Row Processing (4-channel, Mixed RAW/VQ)
; ==========================================================================
; Macro-based: each phase uses macros expanded per channel.
; Single point of maintenance for all 4 channels.
;
; Two-Phase Trigger Architecture:
;   Phase 1 (PREPARE): IRQ enabled. Lookup pitch, sample pointers, and
;     first codebook vector (VQ) or raw start address (RAW).
;   Phase 2 (COMMIT): Three sub-phases for minimal IRQ blackout:
;     2A: Deactivate triggered channels (atomic writes, no SEI)
;     2B: Setup all variables (IRQs enabled, channels inactive)
;     2C: Activate channels (brief SEI, ~40 cycles)
;
; Entry: JMP from main_loop when seq_tick reaches seq_speed
; Exit:  falls through to @pr_done (used by song_player.asm)
; ==========================================================================

VOL_CHANGE_ASM = 61  ; volume-only event marker (no retrigger)

; ==========================================================================
; DISPATCH_EVENT — Check if channel has event on this row
; ==========================================================================
; :1 = channel (0-3)
; ==========================================================================
.macro DISPATCH_EVENT
    lda seq_evt_row+:1
    cmp seq_local_row+:1
    bne @+
    ldx #:1
    jsr parse_event
    lda #$FF
    sta evt_trigger+:1
@
.endm

; ==========================================================================
; PREPARE_CHANNEL — Phase 1: lookup pitch, sample, first vector
; ==========================================================================
; :1 = channel (0-3)
; ==========================================================================
.macro PREPARE_CHANNEL
    lda evt_trigger+:1
    bne @prep_active_:1
    jmp @prep_done_:1
@prep_active_:1:
    lda evt_note+:1
    beq @prep_skip_:1           ; note=0 → skip
    cmp #VOL_CHANGE_ASM          ; volume-only event?
    bne @prep_note_:1           ; no → normal note
    ; Volume-only: update vol_shift, clear trigger (keep playing)
.if VOLUME_CONTROL = 1
    lda evt_vol+:1
    asl
    asl
    asl
    asl
    sta trk:1_vol_shift
.endif
    lda #0
    sta evt_trigger+:1           ; prevent deactivate/reactivate
@prep_skip_:1:
    jmp @prep_done_:1
@prep_note_:1:

    sec
    sbc #1
    tax
    lda NOTE_PITCH_LO,x
    sta prep:1_pitch_lo
    lda NOTE_PITCH_HI,x
    sta prep:1_pitch_hi

    lda evt_inst+:1
    and #$7F
    tax
    lda SAMPLE_START_LO,x
    sta prep:1_stream_lo
    lda SAMPLE_START_HI,x
    sta prep:1_stream_hi
    lda SAMPLE_END_LO,x
    sta prep:1_end_lo
    lda SAMPLE_END_HI,x
    sta prep:1_end_hi

    lda SAMPLE_MODE,x            ; 0=VQ, non-zero=RAW
    sta prep:1_mode
.ifdef USE_BANKING
    lda SAMPLE_PORTB,x
    sta prep:1_portb
    lda SAMPLE_BANK_SEQ_OFF,x
    sta prep:1_seq_off
    lda SAMPLE_N_BANKS,x
    sta prep:1_n_banks
    lda SAMPLE_DATA_HI,x
    sta prep:1_data_hi
    lda prep:1_mode              ; reload (banking reads clobbered A)
.endif
    bne @prep_raw_:1

    ; VQ: look up first codebook vector from index stream
    lda prep:1_stream_lo
    sta trk_ptr
    lda prep:1_stream_hi
    sta trk_ptr+1
    ldy #0
.ifdef USE_BANKING
    ; Minimal SEI window: bank switch + single byte read + restore
    ; (25 cycles, down from 41 — trk_ptr setup moved outside SEI)
    sei
    lda prep:1_portb
    sta PORTB
    lda (trk_ptr),y              ; single bank read
    tax                          ; save index in X
    lda #PORTB_MAIN
    sta PORTB
    cli
    txa
    tay
.else
    lda (trk_ptr),y
    tay
.endif
    lda VQ_LO,y
    sta prep:1_vq_lo
    lda VQ_HI,y
    sta prep:1_vq_hi
    jmp @prep_vol_:1

@prep_raw_:1:
    ; RAW: sample_ptr = raw data start address
    lda prep:1_stream_lo
    sta prep:1_vq_lo
    lda prep:1_stream_hi
    sta prep:1_vq_hi

@prep_vol_:1:
.if VOLUME_CONTROL = 1
    lda evt_vol+:1
    asl
    asl
    asl
    asl
    sta prep:1_vol
.endif
@prep_done_:1:
.endm

; ==========================================================================
; DEACTIVATE_CHANNEL — Phase 2A: atomic deactivate + note-off
; ==========================================================================
; :1 = channel (0-3)
; :2 = AUDC register (AUDC1..AUDC4)
; ==========================================================================
.macro DEACTIVATE_CHANNEL
    lda evt_trigger+:1
    beq @deact_done_:1
    lda #0
    sta trk:1_active
    lda evt_note+:1
    bne @deact_done_:1
    ; Note-off: silence and clear trigger
    lda #SILENCE
    sta :2
    lda #0
    sta evt_trigger+:1
@deact_done_:1:
.endm

; ==========================================================================
; SETUP_CHANNEL — Phase 2B: write all channel state (IRQ enabled)
; ==========================================================================
; :1 = channel (0-3)
; ==========================================================================
.macro SETUP_CHANNEL
    lda evt_trigger+:1
    bne @setup_active_:1
    jmp @setup_done_:1
@setup_active_:1:

    lda #0
    sta trk:1_vector_offset

    ; Pitch detection: step==$0100 and vol==15 means "no pitch"
    lda prep:1_pitch_hi
    cmp #$01
    bne @setup_pitch_:1
    lda prep:1_pitch_lo
    bne @setup_pitch_:1
.if VOLUME_CONTROL = 1
    lda evt_vol+:1
    cmp #15
    bne @setup_pitch_:1
.endif
    lda #0
    sta prep:1_has_pitch
    jmp @setup_stream_:1

@setup_pitch_:1:
    lda #0
    sta trk:1_pitch_frac
    sta trk:1_pitch_int
    lda prep:1_pitch_lo
    sta trk:1_pitch_step
    lda prep:1_pitch_hi
    sta trk:1_pitch_step+1
    lda #$FF
    sta prep:1_has_pitch

@setup_stream_:1:
    lda prep:1_stream_lo
    sta trk:1_stream_ptr
    lda prep:1_stream_hi
    sta trk:1_stream_ptr+1
    lda prep:1_end_lo
    sta trk:1_stream_end
    lda prep:1_end_hi
    sta trk:1_stream_end+1
    lda prep:1_vq_lo
    sta trk:1_sample_ptr
    lda prep:1_vq_hi
    sta trk:1_sample_ptr+1
.if VOLUME_CONTROL = 1
    lda prep:1_vol
    sta trk:1_vol_shift
.endif

    ; SMC: set tick handler based on mode (VQ/RAW) and pitch
    lda prep:1_has_pitch
    bne @setup_smc_pitch_:1
    ; No-pitch dispatch
    lda prep:1_mode
    bne @setup_smc_np_raw_:1
    lda #<ch:1_vq_no_pitch
    ldx #>ch:1_vq_no_pitch
    jmp @setup_smc_store_:1
@setup_smc_np_raw_:1:
    lda #<ch:1_raw_no_pitch
    ldx #>ch:1_raw_no_pitch
    jmp @setup_smc_store_:1
@setup_smc_pitch_:1:
    lda prep:1_mode
    bne @setup_smc_p_raw_:1
    lda #<ch:1_vq_pitch
    ldx #>ch:1_vq_pitch
    jmp @setup_smc_store_:1
@setup_smc_p_raw_:1:
    lda #<ch:1_raw_pitch
    ldx #>ch:1_raw_pitch
@setup_smc_store_:1:
    sta ch:1_tick_jmp
    stx ch:1_tick_jmp+1

.ifdef USE_BANKING
    lda prep:1_portb
    sta ch:1_bank
    lda prep:1_seq_off
    sta ch:1_bank_seq_idx
    lda prep:1_n_banks
    sec
    sbc #1
    sta ch:1_banks_left
    lda prep:1_data_hi
    sta ch:1_data_hi
.endif
@setup_done_:1:
.endm

; ==========================================================================
; ACTIVATE_CHANNEL — Phase 2C: set active flag (called under SEI)
; ==========================================================================
; :1 = channel (0-3)
; ==========================================================================
.macro ACTIVATE_CHANNEL
    lda evt_trigger+:1
    beq @activate_done_:1
    lda #$FF
    sta trk:1_active
@activate_done_:1:
.endm


; ==========================================================================
; PROCESS_ROW — Main code
; ==========================================================================

    ; --- Clear trigger flags ---
    lda #0
    sta evt_trigger
    sta evt_trigger+1
    sta evt_trigger+2
    sta evt_trigger+3

    ; --- Event dispatch ---
    DISPATCH_EVENT 0
    DISPATCH_EVENT 1
    DISPATCH_EVENT 2
    DISPATCH_EVENT 3

    ; --- Phase 1: Prepare (IRQ enabled) ---
    PREPARE_CHANNEL 0
    PREPARE_CHANNEL 1
    PREPARE_CHANNEL 2
    PREPARE_CHANNEL 3

    ; =========================================================================
    ; PHASE 2: COMMIT
    ; =========================================================================

    ; --- 2A: Deactivate triggered channels (no SEI, atomic writes) ---
    DEACTIVATE_CHANNEL 0, AUDC1
    DEACTIVATE_CHANNEL 1, AUDC2
    DEACTIVATE_CHANNEL 2, AUDC3
    DEACTIVATE_CHANNEL 3, AUDC4

    ; --- 2B: Setup (IRQs enabled, channels inactive → safe) ---
    SETUP_CHANNEL 0
    SETUP_CHANNEL 1
    SETUP_CHANNEL 2
    SETUP_CHANNEL 3

    ; --- 2C: Activate (brief SEI, ~40 cycles) ---
    sei
    ACTIVATE_CHANNEL 0
    ACTIVATE_CHANNEL 1
    ACTIVATE_CHANNEL 2
    ACTIVATE_CHANNEL 3
    cli

    ; =========================================================================
    ; ADVANCE LOCAL ROWS — Per-channel pattern position
    ; =========================================================================
    ldx #3
@pr_advance_local:
    inc seq_local_row,x
    lda seq_local_row,x
    cmp seq_ptn_len,x
    bcc @pr_no_wrap

    ; Pattern wrap
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
    bpl @pr_advance_local

    ; =========================================================================
    ; ADVANCE GLOBAL ROW — Songline progression
    ; =========================================================================
    inc seq_row
    lda seq_row
    cmp seq_max_len
    bcc @pr_done

    ; Songline wrap
    lda #0
    sta seq_row

    inc seq_songline
    lda seq_songline
    cmp #SONG_LENGTH
    bcc @pr_load_new

    ; Song end
.if KEY_CONTROL = 1
    lda #0
    sta seq_songline
.else
    lda #0
    sta seq_songline
    sta seq_playing
    jmp @pr_done
.endif

@pr_load_new:
    jsr seq_load_songline

@pr_done:
    ; === END OF PROCESS_ROW ===
