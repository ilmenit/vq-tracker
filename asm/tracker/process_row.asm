; ==========================================================================
; PROCESS_ROW.ASM - Row Processing (INCLUDED)
; ==========================================================================
; This file is included in song_player.asm BEFORE the main loop.
; It does NOT end with RTS - song_player.asm adds JMP after the include.
;
; Placement before main_loop keeps branch distances short for the common
; case (skipping row processing), saving ~3 cycles per frame on average.
;
; Two-Phase Trigger Architecture:
; ===============================
; PHASE 1 (PREPARE): Table lookups with IRQ ENABLED
;   - Pitch table lookups (NOTE_PITCH_LO/HI)
;   - Sample directory lookups (SAMPLE_START/END)
;   - VQ cache pre-load
;   - Results stored in staging area (prep*_*)
;
; PHASE 2 (COMMIT): Fast writes with IRQ DISABLED
;   - Copy staging area to channel state (trk*_*)
;   - Minimal time in SEI block (~60 cycles/channel)
;
; Performance:
;   - Old design: ~480 cycles with IRQ disabled (missed 2+ IRQs at 8kHz)
;   - New design: ~180 cycles with IRQ disabled (miss 0-1 IRQs)
;   - Improvement: 62% reduction in IRQ-disabled time
;
; Entry: JMP from main_loop when seq_tick reaches seq_speed
; Exit:  JMP back to ml_check_state_change (added by song_player.asm)
; ==========================================================================

    ; =========================================================================
    ; Clear trigger flags for all channels
    ; =========================================================================
    ; Trigger flags indicate which channels have events on this row.
    ; $FF = event pending, $00 = no event
    lda #0
    sta evt_trigger
    sta evt_trigger+1
    sta evt_trigger+2
    ; A = 0, X/Y = undefined
    
    ; =========================================================================
    ; EVENT DISPATCH - Check if each channel has an event on this row
    ; =========================================================================
    ; For each channel: if seq_evt_row[ch] == seq_local_row[ch], there's
    ; an event to process. Call parse_event to decode it.
    ;
    ; NOTE: We check each channel independently because patterns can have
    ; different lengths, so channels may be on different "local" rows.
    
    ; --- Channel 0 ---
    lda seq_evt_row             ; A = next event row for CH0
    cmp seq_local_row           ; Compare with current local row
    bne @pr_no_ch0              ; No match = no event on this row
    ldx #0                      ; X = channel index for parse_event
    jsr parse_event             ; Parse event, clobbers A/X/Y
    lda #$FF
    sta evt_trigger             ; Mark CH0 as having a pending event
@pr_no_ch0:
    ; After: A = $FF or garbage, X/Y = garbage

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
    ; After event dispatch: evt_trigger[] flags set, evt_note/inst/vol[] populated

    ; =========================================================================
    ; PHASE 1: PREPARE (IRQ enabled - slow table lookups happen here)
    ; =========================================================================
    ; For each triggered channel with a note (not note-off):
    ;   1. Look up pitch from NOTE_PITCH tables (8.8 fixed-point)
    ;   2. Look up sample pointers from SAMPLE_* tables
    ;   3. Pre-load first VQ vector address from codebook
    ;   4. (Optional) Prepare volume scaling
    ;
    ; This phase runs with IRQ ENABLED, so table lookups can be interrupted.
    ; All results go to staging area (prep*_*), not directly to channel state.
    
    ; --- Prepare Channel 0 ---
    lda evt_trigger             ; Check if CH0 has pending event
    beq @prep_done_0            ; No event = skip preparation
    lda evt_note                ; A = note value (0=off, 1-48=note)
    beq @prep_done_0            ; Note-off (0) needs no preparation
    
    ; --- Pitch lookup (note 1-48 -> index 0-47) ---
    ; Note values are 1-based (C-1=1, C#1=2, ..., B-4=48)
    ; Table indices are 0-based, so subtract 1
    sec
    sbc #1                      ; A = note - 1 (0-47)
    tax                         ; X = table index
    lda NOTE_PITCH_LO,x         ; A = pitch step low byte
    sta prep0_pitch_lo
    lda NOTE_PITCH_HI,x         ; A = pitch step high byte
    sta prep0_pitch_hi
    ; X = note index (0-47), free to reuse
    
    ; --- Sample stream lookup ---
    ; Look up sample start/end pointers from directory
    lda evt_inst                ; A = instrument (0-127)
    and #$7F                    ; Ensure valid range (shouldn't be needed but safe)
    tax                         ; X = instrument index
    lda SAMPLE_START_LO,x
    sta prep0_stream_lo
    lda SAMPLE_START_HI,x
    sta prep0_stream_hi
    lda SAMPLE_END_LO,x
    sta prep0_end_lo
    lda SAMPLE_END_HI,x
    sta prep0_end_hi
    ; X = instrument index, free to reuse
    
    ; --- VQ cache pre-load ---
    ; Read first VQ codebook index from stream and resolve to vector address
    lda prep0_stream_lo
    sta trk_ptr
    lda prep0_stream_hi
    sta trk_ptr+1               ; trk_ptr = stream start address
    ldy #0
    lda (trk_ptr),y             ; A = first VQ codebook index
    tay                         ; Y = VQ index for table lookup
    lda VQ_LO,y                 ; A = vector address low byte
    sta prep0_vq_lo
    lda VQ_HI,y                 ; A = vector address high byte
    sta prep0_vq_hi
    ; Y = VQ index, free to reuse
    
.if VOLUME_CONTROL = 1
    ; --- Volume staging ---
    ; Shift volume left 4 bits for VOLUME_SCALE table index
    ; VOLUME_SCALE is indexed by (volume << 4) | sample_value
    lda evt_vol                 ; A = volume (0-15)
    asl
    asl
    asl
    asl                         ; A = volume << 4 ($00, $10, $20, ..., $F0)
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
    
.if VOLUME_CONTROL = 1
    lda evt_vol+2
    asl
    asl
    asl
    asl
    sta prep2_vol
.endif
@prep_done_2:

    ; =========================================================================
    ; PHASE 2: COMMIT (IRQ disabled - fast writes only, ~60 cyc/channel)
    ; =========================================================================
    ; Copy prepared values from staging area to channel state.
    ; This is the critical section - keep it as short as possible!
    
    sei                         ; *** IRQ DISABLED ***
    
    ; --- Commit Channel 0 ---
    lda evt_trigger
    beq @commit_done_0
    lda evt_note
    bne @commit_note_0
    
    ; Note-off: silence channel immediately
    lda #0
    sta trk0_active
    lda #SILENCE
    sta AUDC1
    jmp @commit_done_0
    
@commit_note_0:
    ; Note-on: copy all staging values to channel state
    lda #0
    sta trk0_active             ; Deactivate during setup
    sta trk0_pitch_frac
    sta trk0_pitch_int
    sta trk0_vector_offset
    lda prep0_pitch_lo
    sta trk0_pitch_step
    lda prep0_pitch_hi
    sta trk0_pitch_step+1
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
    lda #$FF
    sta trk0_active             ; Activate channel
@commit_done_0:

    ; --- Commit Channel 1 ---
    lda evt_trigger+1
    beq @commit_done_1
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
    sta trk1_pitch_frac
    sta trk1_pitch_int
    sta trk1_vector_offset
    lda prep1_pitch_lo
    sta trk1_pitch_step
    lda prep1_pitch_hi
    sta trk1_pitch_step+1
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
    lda #$FF
    sta trk1_active
@commit_done_1:

    ; --- Commit Channel 2 ---
    lda evt_trigger+2
    beq @commit_done_2
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
    sta trk2_pitch_frac
    sta trk2_pitch_int
    sta trk2_vector_offset
    lda prep2_pitch_lo
    sta trk2_pitch_step
    lda prep2_pitch_hi
    sta trk2_pitch_step+1
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
    lda #$FF
    sta trk2_active
@commit_done_2:

    cli                         ; *** IRQ RE-ENABLED ***
    
    ; =========================================================================
    ; ADVANCE LOCAL ROWS - Per-channel pattern position
    ; =========================================================================
    ; Each channel has its own pattern with potentially different length.
    ; Local row tracks position within each channel's pattern.
    ; When a channel's local row reaches pattern length, it wraps to row 0
    ; and resets the event pointer to pattern start.
    ;
    ; Loop processes channels 2, 1, 0 (X counts down from 2)
    
    ldx #2                      ; Start with channel 2
@pr_advance_local:
    inc seq_local_row,x         ; Advance local row
    lda seq_local_row,x         ; A = new local row
    cmp seq_ptn_len,x           ; Compare with pattern length
    bcc @pr_no_wrap             ; If row < length, no wrap needed
    
    ; --- Pattern wrap ---
    ; Reset local row to 0 and reload first event pointer
    lda #0
    sta seq_local_row,x         ; Reset to row 0
    
    ; Reset event pointer to pattern start
    lda seq_ptn_start_lo,x
    sta seq_evt_ptr_lo,x
    sta trk_ptr
    lda seq_ptn_start_hi,x
    sta seq_evt_ptr_hi,x
    sta trk_ptr+1               ; trk_ptr = pattern start address
    
    ; Read first event's row number
    ; NOTE: Must save X because (zp),y clobbers nothing but we need X after
    stx parse_temp              ; Save channel index
    ldy #0
    lda (trk_ptr),y             ; A = first event's row number
    ldx parse_temp              ; Restore channel index
    sta seq_evt_row,x           ; Set next event row for this channel
    
@pr_no_wrap:
    dex                         ; Next channel (2 -> 1 -> 0)
    bpl @pr_advance_local       ; Loop while X >= 0
    ; Exit: X = $FF, A/Y = garbage
    
    ; =========================================================================
    ; ADVANCE GLOBAL ROW - Songline progression
    ; =========================================================================
    ; Global row is the "master clock" that determines when to advance songline.
    ; It counts from 0 to seq_max_len-1 (longest pattern in current songline).
    ; When it wraps, we advance to the next songline.
    
    inc seq_row                 ; Advance global row
    lda seq_row                 ; A = new global row
    cmp seq_max_len             ; Compare with longest pattern
    bcc @pr_done                ; If row < max_len, continue
    
    ; --- Songline wrap ---
    lda #0
    sta seq_row                 ; Reset global row to 0
    
    inc seq_songline            ; Advance to next songline
    lda seq_songline            ; A = new songline
    cmp #SONG_LENGTH            ; Compare with song length (from SONG_CFG)
    bcc @pr_load_new            ; If songline < song_length, load it
    
    ; --- Song wrap ---
    ; End of song reached, loop back to beginning
    lda #0
    sta seq_songline            ; Reset to songline 0
    
@pr_load_new:
    jsr seq_load_songline
    
@pr_done:
    ; === END OF PROCESS_ROW ===
    ; song_player.asm adds JMP ml_check_state_change after this include
