; ==========================================================================
; SEQ_INIT.ASM - Sequencer Initialization (SUBROUTINE)
; ==========================================================================
; Initializes all sequencer state for playback.
; Called at startup and when user presses R (restart).
;
; Initializes:
;   - Playback position (songline 0, row 0, tick 0)
;   - Default speed and pattern length
;   - Per-channel state (last inst/vol, event pointers)
;   - Volume control (if enabled)
;   - Audio channels (silenced)
;   - Display color (stopped state)
;
; After init, calls seq_load_songline to setup first songline.
;
; Input:  None
; Output: All sequencer state initialized, ready to play
; ==========================================================================

seq_init:
    ; =========================================================================
    ; Core sequencer state
    ; =========================================================================
    lda #0
    sta seq_songline            ; Start at songline 0
    sta seq_row                 ; Start at row 0
    sta seq_tick                ; Start at tick 0
    sta seq_playing             ; Start stopped
    sta last_playing            ; Previous state = stopped
    sta vcount_phase            ; VCOUNT frame detection
    
    ; =========================================================================
    ; Default configuration
    ; =========================================================================
    lda #6
    sta seq_speed               ; Default: 6 ticks per row (~8.3 rows/sec)
    lda #64
    sta seq_max_len             ; Default: 64 rows (overwritten by songline)
    lda #$FF
    sta last_key_code           ; No key pressed
    
    ; =========================================================================
    ; Per-channel state (loop through channels 2, 1, 0)
    ; =========================================================================
    ldx #2
@si_loop:
    lda #0
    sta seq_last_inst,x         ; Last instrument = 0
    sta evt_trigger,x           ; No pending triggers
    sta seq_local_row,x         ; Local row = 0
    sta evt_note,x              ; Clear event data
    sta evt_inst,x
    sta evt_vol,x
    
    lda #$FF
    sta seq_evt_row,x           ; Next event row = $FF (none pending)
    
    lda #15
    sta seq_last_vol,x          ; Last volume = max (15)
    
    lda #64
    sta seq_ptn_len,x           ; Default pattern length
    
    dex
    bpl @si_loop
    
    ; =========================================================================
    ; Volume control initialization (if enabled)
    ; =========================================================================
.if VOLUME_CONTROL = 1
    lda #$F0                    ; Max volume shifted ($F << 4)
    sta trk0_vol_shift
    sta trk1_vol_shift
    sta trk2_vol_shift
.endif
    
    ; =========================================================================
    ; Audio channel state
    ; =========================================================================
    lda #0
    sta trk0_active             ; Channel 0 inactive
    sta trk1_active             ; Channel 1 inactive
    sta trk2_active             ; Channel 2 inactive
    
    lda #SILENCE                ; $10 = volume-only mode, volume 0
    sta AUDC1
    sta AUDC2
    sta AUDC3
    
    ; =========================================================================
    ; Display state
    ; =========================================================================
    lda #COL_STOPPED            ; Black background
    sta COLBK
    
    ; =========================================================================
    ; Load first songline
    ; =========================================================================
    jsr seq_load_songline
    
    rts
