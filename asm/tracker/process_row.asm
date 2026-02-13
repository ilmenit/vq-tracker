; ==========================================================================
; PROCESS_ROW.ASM - Row Processing (4-channel, Mixed RAW/VQ)
; ==========================================================================
; Two-Phase Trigger Architecture for all 4 POKEY channels.
; Entry: JMP from main_loop when seq_tick reaches seq_speed
; Exit:  JMP back to ml_after_row
;
; Phase 1 (PREPARE): IRQ enabled. Lookup pitch, sample pointers, and
;   first codebook vector (VQ) or raw start address (RAW).
; Phase 2 (COMMIT): Three sub-phases to avoid long IRQ blackouts:

VOL_CHANGE_ASM = 61  ; volume-only event marker (no retrigger)
;   2A: Deactivate triggered channels (no SEI, atomic writes)
;   2B: Setup all variables (IRQs enabled, safe while channels inactive)
;   2C: Activate channels (brief SEI, ~40 cycles max)
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
    bne @prep_active_0
    jmp @prep_done_0
@prep_active_0:
    lda evt_note
    beq @vol_skip_0           ; note=0 → skip
    cmp #VOL_CHANGE_ASM          ; volume-only event?
    bne @prep_note_0          ; no → normal note
    ; Volume-only: update vol_shift, clear trigger (keep channel playing)
.if VOLUME_CONTROL = 1
    lda evt_vol
    asl
    asl
    asl
    asl
    sta trk0_vol_shift
.endif
    lda #0
    sta evt_trigger      ; prevent deactivate/reactivate
@vol_skip_0:
    jmp @prep_done_0
@prep_note_0:
    
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
.ifdef USE_BANKING
    lda SAMPLE_PORTB,x
    sta prep0_portb
    lda SAMPLE_BANK_SEQ_OFF,x
    sta prep0_seq_off
    lda SAMPLE_N_BANKS,x
    sta prep0_n_banks
    lda prep0_mode               ; reload mode (banking reads clobbered A)
.endif
    bne @prep0_raw
    
    ; VQ: look up first codebook vector from index stream
.ifdef USE_BANKING
    sei                          ; protect bank switch from IRQ
    lda prep0_portb
    sta PORTB
.endif
    lda prep0_stream_lo
    sta trk_ptr
    lda prep0_stream_hi
    sta trk_ptr+1
    ldy #0
    lda (trk_ptr),y
    tay
.ifdef USE_BANKING
    lda #PORTB_MAIN
    sta PORTB                    ; restore main RAM
    cli
.endif
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
    bne @prep_active_1
    jmp @prep_done_1
@prep_active_1:
    lda evt_note+1
    beq @vol_skip_1           ; note=0 → skip
    cmp #VOL_CHANGE_ASM          ; volume-only event?
    bne @prep_note_1          ; no → normal note
    ; Volume-only: update vol_shift, clear trigger (keep channel playing)
.if VOLUME_CONTROL = 1
    lda evt_vol+1
    asl
    asl
    asl
    asl
    sta trk1_vol_shift
.endif
    lda #0
    sta evt_trigger+1      ; prevent deactivate/reactivate
@vol_skip_1:
    jmp @prep_done_1
@prep_note_1:
    
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
.ifdef USE_BANKING
    lda SAMPLE_PORTB,x
    sta prep1_portb
    lda SAMPLE_BANK_SEQ_OFF,x
    sta prep1_seq_off
    lda SAMPLE_N_BANKS,x
    sta prep1_n_banks
    lda prep1_mode
.endif
    bne @prep1_raw
    
.ifdef USE_BANKING
    sei
    lda prep1_portb
    sta PORTB
.endif
    lda prep1_stream_lo
    sta trk_ptr
    lda prep1_stream_hi
    sta trk_ptr+1
    ldy #0
    lda (trk_ptr),y
    tay
.ifdef USE_BANKING
    lda #PORTB_MAIN
    sta PORTB
    cli
.endif
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
    bne @prep_active_2
    jmp @prep_done_2
@prep_active_2:
    lda evt_note+2
    beq @vol_skip_2           ; note=0 → skip
    cmp #VOL_CHANGE_ASM          ; volume-only event?
    bne @prep_note_2          ; no → normal note
    ; Volume-only: update vol_shift, clear trigger (keep channel playing)
.if VOLUME_CONTROL = 1
    lda evt_vol+2
    asl
    asl
    asl
    asl
    sta trk2_vol_shift
.endif
    lda #0
    sta evt_trigger+2      ; prevent deactivate/reactivate
@vol_skip_2:
    jmp @prep_done_2
@prep_note_2:
    
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
.ifdef USE_BANKING
    lda SAMPLE_PORTB,x
    sta prep2_portb
    lda SAMPLE_BANK_SEQ_OFF,x
    sta prep2_seq_off
    lda SAMPLE_N_BANKS,x
    sta prep2_n_banks
    lda prep2_mode
.endif
    bne @prep2_raw
    
.ifdef USE_BANKING
    sei
    lda prep2_portb
    sta PORTB
.endif
    lda prep2_stream_lo
    sta trk_ptr
    lda prep2_stream_hi
    sta trk_ptr+1
    ldy #0
    lda (trk_ptr),y
    tay
.ifdef USE_BANKING
    lda #PORTB_MAIN
    sta PORTB
    cli
.endif
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
    bne @prep_active_3
    jmp @prep_done_3
@prep_active_3:
    lda evt_note+3
    beq @vol_skip_3           ; note=0 → skip
    cmp #VOL_CHANGE_ASM          ; volume-only event?
    bne @prep_note_3          ; no → normal note
    ; Volume-only: update vol_shift, clear trigger (keep channel playing)
.if VOLUME_CONTROL = 1
    lda evt_vol+3
    asl
    asl
    asl
    asl
    sta trk3_vol_shift
.endif
    lda #0
    sta evt_trigger+3      ; prevent deactivate/reactivate
@vol_skip_3:
    jmp @prep_done_3
@prep_note_3:
    
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
.ifdef USE_BANKING
    lda SAMPLE_PORTB,x
    sta prep3_portb
    lda SAMPLE_BANK_SEQ_OFF,x
    sta prep3_seq_off
    lda SAMPLE_N_BANKS,x
    sta prep3_n_banks
    lda prep3_mode
.endif
    bne @prep3_raw
    
.ifdef USE_BANKING
    sei
    lda prep3_portb
    sta PORTB
.endif
    lda prep3_stream_lo
    sta trk_ptr
    lda prep3_stream_hi
    sta trk_ptr+1
    ldy #0
    lda (trk_ptr),y
    tay
.ifdef USE_BANKING
    lda #PORTB_MAIN
    sta PORTB
    cli
.endif
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
    ; =========================================================================
    ; PHASE 2: COMMIT (Restructured for minimal SEI window)
    ; =========================================================================
    ; Three sub-phases to avoid long IRQ blackouts:
    ;   2A: DEACTIVATE triggered channels (no SEI — atomic single-byte writes)
    ;   2B: SETUP all variables (IRQs enabled — channels are inactive)
    ;   2C: ACTIVATE channels (brief SEI — ~40 cycles max)
    ;
    ; Why this is safe: once trkN_active=0, the IRQ handler jumps to
    ; chN_skip immediately, never touching any channel state or SMC
    ; locations. So writing pitch/stream/SMC/banking with IRQs enabled
    ; is completely safe while the channel is deactivated.
    ; =========================================================================

    ; =========================================================================
    ; PHASE 2A: DEACTIVATE triggered channels
    ; =========================================================================
    ; Single-byte STA to trkN_active is atomic on 6502.
    ; No SEI needed — the IRQ handler sees active=0 and skips the channel.
    ; Note-off channels are fully handled here (deactivate + silence).

    lda evt_trigger
    beq @deact_done_0
    lda #0
    sta trk0_active
    lda evt_note
    bne @deact_done_0
    ; Note-off: silence and clear trigger (no setup/activate needed)
    lda #SILENCE
    sta AUDC1
    lda #0
    sta evt_trigger             ; clear trigger so phases 2B/2C skip it
@deact_done_0:

    lda evt_trigger+1
    beq @deact_done_1
    lda #0
    sta trk1_active
    lda evt_note+1
    bne @deact_done_1
    lda #SILENCE
    sta AUDC2
    lda #0
    sta evt_trigger+1
@deact_done_1:

    lda evt_trigger+2
    beq @deact_done_2
    lda #0
    sta trk2_active
    lda evt_note+2
    bne @deact_done_2
    lda #SILENCE
    sta AUDC3
    lda #0
    sta evt_trigger+2
@deact_done_2:

    lda evt_trigger+3
    beq @deact_done_3
    lda #0
    sta trk3_active
    lda evt_note+3
    bne @deact_done_3
    lda #SILENCE
    sta AUDC4
    lda #0
    sta evt_trigger+3
@deact_done_3:

    ; =========================================================================
    ; PHASE 2B: SETUP (IRQs enabled — channels are inactive)
    ; =========================================================================
    ; All triggered note-on channels have trkN_active=0, so the IRQ handler
    ; completely skips them. We can safely write to all channel variables
    ; and SMC locations without SEI.

    ; --- Setup Channel 0 ---
    lda evt_trigger
    bne @setup_active_0
    jmp @setup_done_0
@setup_active_0:

    lda #0
    sta trk0_vector_offset
    
    ; Pitch setup
    lda prep0_pitch_hi
    cmp #$01
    bne @ch0_setup_pitch
    lda prep0_pitch_lo
    bne @ch0_setup_pitch
.if VOLUME_CONTROL = 1
    lda evt_vol
    cmp #15
    bne @ch0_setup_pitch
.endif
    
    lda #0
    sta prep0_has_pitch       ; flag: no pitch
    jmp @ch0_setup_stream
    
@ch0_setup_pitch:
    lda #0
    sta trk0_pitch_frac
    sta trk0_pitch_int
    lda prep0_pitch_lo
    sta trk0_pitch_step
    lda prep0_pitch_hi
    sta trk0_pitch_step+1
    lda #$FF
    sta prep0_has_pitch       ; flag: has pitch
    
@ch0_setup_stream:
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

    ; SMC: set tick handler based on mode (VQ/RAW) and pitch
    lda prep0_has_pitch
    bne @ch0_smc_pitch
    ; No-pitch dispatch
    lda prep0_mode
    bne @ch0_smc_np_raw
    lda #<ch0_vq_no_pitch
    ldx #>ch0_vq_no_pitch
    jmp @ch0_smc_store
@ch0_smc_np_raw:
    lda #<ch0_raw_no_pitch
    ldx #>ch0_raw_no_pitch
    jmp @ch0_smc_store
@ch0_smc_pitch:
    ; Pitch dispatch
    lda prep0_mode
    bne @ch0_smc_p_raw
    lda #<ch0_vq_pitch
    ldx #>ch0_vq_pitch
    jmp @ch0_smc_store
@ch0_smc_p_raw:
    lda #<ch0_raw_pitch
    ldx #>ch0_raw_pitch
@ch0_smc_store:
    sta ch0_tick_jmp
    stx ch0_tick_jmp+1
    
@ch0_setup_bank:
.ifdef USE_BANKING
    lda prep0_portb
    sta ch0_bank
    lda prep0_seq_off
    sta ch0_bank_seq_idx
    lda prep0_n_banks
    sec
    sbc #1
    sta ch0_banks_left
.endif
@setup_done_0:

    ; --- Setup Channel 1 ---
    lda evt_trigger+1
    bne @setup_active_1
    jmp @setup_done_1
@setup_active_1:

    lda #0
    sta trk1_vector_offset
    
    lda prep1_pitch_hi
    cmp #$01
    bne @ch1_setup_pitch
    lda prep1_pitch_lo
    bne @ch1_setup_pitch
.if VOLUME_CONTROL = 1
    lda evt_vol+1
    cmp #15
    bne @ch1_setup_pitch
.endif
    
    lda #0
    sta prep1_has_pitch       ; flag: no pitch
    jmp @ch1_setup_stream
    
@ch1_setup_pitch:
    lda #0
    sta trk1_pitch_frac
    sta trk1_pitch_int
    lda prep1_pitch_lo
    sta trk1_pitch_step
    lda prep1_pitch_hi
    sta trk1_pitch_step+1
    lda #$FF
    sta prep1_has_pitch       ; flag: has pitch
    
@ch1_setup_stream:
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

    ; SMC: set tick handler based on mode (VQ/RAW) and pitch
    lda prep1_has_pitch
    bne @ch1_smc_pitch
    ; No-pitch dispatch
    lda prep1_mode
    bne @ch1_smc_np_raw
    lda #<ch1_vq_no_pitch
    ldx #>ch1_vq_no_pitch
    jmp @ch1_smc_store
@ch1_smc_np_raw:
    lda #<ch1_raw_no_pitch
    ldx #>ch1_raw_no_pitch
    jmp @ch1_smc_store
@ch1_smc_pitch:
    ; Pitch dispatch
    lda prep1_mode
    bne @ch1_smc_p_raw
    lda #<ch1_vq_pitch
    ldx #>ch1_vq_pitch
    jmp @ch1_smc_store
@ch1_smc_p_raw:
    lda #<ch1_raw_pitch
    ldx #>ch1_raw_pitch
@ch1_smc_store:
    sta ch1_tick_jmp
    stx ch1_tick_jmp+1
    
@ch1_setup_bank:
.ifdef USE_BANKING
    lda prep1_portb
    sta ch1_bank
    lda prep1_seq_off
    sta ch1_bank_seq_idx
    lda prep1_n_banks
    sec
    sbc #1
    sta ch1_banks_left
.endif
@setup_done_1:

    ; --- Setup Channel 2 ---
    lda evt_trigger+2
    bne @setup_active_2
    jmp @setup_done_2
@setup_active_2:

    lda #0
    sta trk2_vector_offset
    
    lda prep2_pitch_hi
    cmp #$01
    bne @ch2_setup_pitch
    lda prep2_pitch_lo
    bne @ch2_setup_pitch
.if VOLUME_CONTROL = 1
    lda evt_vol+2
    cmp #15
    bne @ch2_setup_pitch
.endif
    
    lda #0
    sta prep2_has_pitch       ; flag: no pitch
    jmp @ch2_setup_stream
    
@ch2_setup_pitch:
    lda #0
    sta trk2_pitch_frac
    sta trk2_pitch_int
    lda prep2_pitch_lo
    sta trk2_pitch_step
    lda prep2_pitch_hi
    sta trk2_pitch_step+1
    lda #$FF
    sta prep2_has_pitch       ; flag: has pitch
    
@ch2_setup_stream:
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

    ; SMC: set tick handler based on mode (VQ/RAW) and pitch
    lda prep2_has_pitch
    bne @ch2_smc_pitch
    ; No-pitch dispatch
    lda prep2_mode
    bne @ch2_smc_np_raw
    lda #<ch2_vq_no_pitch
    ldx #>ch2_vq_no_pitch
    jmp @ch2_smc_store
@ch2_smc_np_raw:
    lda #<ch2_raw_no_pitch
    ldx #>ch2_raw_no_pitch
    jmp @ch2_smc_store
@ch2_smc_pitch:
    ; Pitch dispatch
    lda prep2_mode
    bne @ch2_smc_p_raw
    lda #<ch2_vq_pitch
    ldx #>ch2_vq_pitch
    jmp @ch2_smc_store
@ch2_smc_p_raw:
    lda #<ch2_raw_pitch
    ldx #>ch2_raw_pitch
@ch2_smc_store:
    sta ch2_tick_jmp
    stx ch2_tick_jmp+1
    
@ch2_setup_bank:
.ifdef USE_BANKING
    lda prep2_portb
    sta ch2_bank
    lda prep2_seq_off
    sta ch2_bank_seq_idx
    lda prep2_n_banks
    sec
    sbc #1
    sta ch2_banks_left
.endif
@setup_done_2:

    ; --- Setup Channel 3 ---
    lda evt_trigger+3
    bne @setup_active_3
    jmp @setup_done_3
@setup_active_3:

    lda #0
    sta trk3_vector_offset
    
    lda prep3_pitch_hi
    cmp #$01
    bne @ch3_setup_pitch
    lda prep3_pitch_lo
    bne @ch3_setup_pitch
.if VOLUME_CONTROL = 1
    lda evt_vol+3
    cmp #15
    bne @ch3_setup_pitch
.endif
    
    lda #0
    sta prep3_has_pitch       ; flag: no pitch
    jmp @ch3_setup_stream
    
@ch3_setup_pitch:
    lda #0
    sta trk3_pitch_frac
    sta trk3_pitch_int
    lda prep3_pitch_lo
    sta trk3_pitch_step
    lda prep3_pitch_hi
    sta trk3_pitch_step+1
    lda #$FF
    sta prep3_has_pitch       ; flag: has pitch
    
@ch3_setup_stream:
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

    ; SMC: set tick handler based on mode (VQ/RAW) and pitch
    lda prep3_has_pitch
    bne @ch3_smc_pitch
    ; No-pitch dispatch
    lda prep3_mode
    bne @ch3_smc_np_raw
    lda #<ch3_vq_no_pitch
    ldx #>ch3_vq_no_pitch
    jmp @ch3_smc_store
@ch3_smc_np_raw:
    lda #<ch3_raw_no_pitch
    ldx #>ch3_raw_no_pitch
    jmp @ch3_smc_store
@ch3_smc_pitch:
    ; Pitch dispatch
    lda prep3_mode
    bne @ch3_smc_p_raw
    lda #<ch3_vq_pitch
    ldx #>ch3_vq_pitch
    jmp @ch3_smc_store
@ch3_smc_p_raw:
    lda #<ch3_raw_pitch
    ldx #>ch3_raw_pitch
@ch3_smc_store:
    sta ch3_tick_jmp
    stx ch3_tick_jmp+1
    
@ch3_setup_bank:
.ifdef USE_BANKING
    lda prep3_portb
    sta ch3_bank
    lda prep3_seq_off
    sta ch3_bank_seq_idx
    lda prep3_n_banks
    sec
    sbc #1
    sta ch3_banks_left
.endif
@setup_done_3:

    ; =========================================================================
    ; PHASE 2C: ACTIVATE (brief SEI — ~40 cycles max)
    ; =========================================================================
    ; All setup is complete. Now activate the channels atomically so they
    ; all start on the same IRQ. The SEI window is at most ~40 cycles
    ; (4 channels × ~10 cycles each), well within any IRQ period.

    sei                         ; *** IRQ DISABLED (brief) ***

    lda evt_trigger
    beq @activate_done_0
    lda #$FF
    sta trk0_active
@activate_done_0:

    lda evt_trigger+1
    beq @activate_done_1
    lda #$FF
    sta trk1_active
@activate_done_1:

    lda evt_trigger+2
    beq @activate_done_2
    lda #$FF
    sta trk2_active
@activate_done_2:

    lda evt_trigger+3
    beq @activate_done_3
    lda #$FF
    sta trk3_active
@activate_done_3:

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
