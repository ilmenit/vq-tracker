; ==========================================================================
; SEQ_INIT.ASM - Sequencer Initialization (4-channel)
; ==========================================================================

seq_init:
    ; Core sequencer state
    lda #0
    sta seq_songline
    sta seq_row
    sta seq_tick
    sta seq_playing
    sta vcount_phase
    
    ; Default configuration
    lda #6
    sta seq_speed
    lda #64
    sta seq_max_len
    lda #$FF
    sta last_key_code
    
    ; Per-channel state (loop through channels 3, 2, 1, 0)
    ldx #3
@si_loop:
    lda #0
    sta seq_last_inst,x
    sta evt_trigger,x
    sta seq_local_row,x
    sta evt_note,x
    sta evt_inst,x
    sta evt_vol,x
    
    lda #$FF
    sta seq_evt_row,x
    
    lda #15
    sta seq_last_vol,x
    
    lda #64
    sta seq_ptn_len,x
    
    dex
    bpl @si_loop
    
    ; Volume control initialization
.if VOLUME_CONTROL = 1
    lda #$F0
    sta trk0_vol_shift
    sta trk1_vol_shift
    sta trk2_vol_shift
    sta trk3_vol_shift
.endif
    
    ; Audio channel state - all 4 channels
    lda #0
    sta trk0_active
    sta trk1_active
    sta trk2_active
    sta trk3_active
    
.ifdef USE_BANKING
    ; Initialize bank SMC to main RAM (silence)
    lda #PORTB_MAIN
    sta ch0_bank
    sta ch1_bank
    sta ch2_bank
    sta ch3_bank
    lda #0
    sta ch0_bank_seq_idx
    sta ch0_banks_left
    sta ch1_bank_seq_idx
    sta ch1_banks_left
    sta ch2_bank_seq_idx
    sta ch2_banks_left
    sta ch3_bank_seq_idx
    sta ch3_banks_left
    ; Restore PORTB to main RAM
    lda #PORTB_MAIN
    sta PORTB
.endif
    
    lda #SILENCE
    sta AUDC1
    sta AUDC2
    sta AUDC3
    sta AUDC4
    
    ; Display state
    lda #COL_STOPPED
    sta COLBK
    
    ; Load first songline
    jsr seq_load_songline
    
    rts
