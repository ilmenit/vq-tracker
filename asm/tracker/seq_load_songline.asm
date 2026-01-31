; ==========================================================================
; SEQ_LOAD_SONGLINE.ASM - Load Songline Configuration (SUBROUTINE)
; ==========================================================================
; Loads pattern assignments and speed from song data for current songline.
; Called when:
;   - Starting playback (via seq_init)
;   - Advancing to a new songline (from process_row)
;
; For each channel, this routine:
;   1. Looks up pattern index from SONG_PTN_CHx table
;   2. Loads pattern length from PATTERN_LEN table
;   3. Loads pattern pointer from PATTERN_PTR_LO/HI tables
;   4. Reads first event's row number
;   5. Updates seq_max_len (longest pattern determines songline length)
;
; REGISTER CONTRACT:
; ==================
; Input:  seq_songline = songline to load (0-255)
; Output: Per-channel pattern pointers and lengths initialized
;         seq_speed = speed from SONG_SPEED table
;         seq_max_len = maximum pattern length
;         seq_last_inst/vol[] = reset to defaults (0, 15)
;         seq_row = 0, seq_local_row[] = 0
; Clobbers: A, X, Y
; Preserves: (nothing)
; Uses ZP:  trk_ptr
; ==========================================================================

seq_load_songline:
    ldx seq_songline            ; X = songline index (used for all lookups)
    
    ; =========================================================================
    ; Load songline speed
    ; =========================================================================
    lda SONG_SPEED,x            ; A = speed for this songline
    sta seq_speed
    
    ; =========================================================================
    ; Reset row counters
    ; =========================================================================
    lda #0
    sta seq_row                 ; Global row = 0
    sta seq_max_len             ; Will be set to max pattern length below
    sta seq_local_row           ; Channel 0 local row = 0
    sta seq_local_row+1         ; Channel 1 local row = 0
    sta seq_local_row+2         ; Channel 2 local row = 0
    ; A = 0 after this block
    
    ; =========================================================================
    ; Channel 0 Pattern Setup
    ; =========================================================================
    ; X = songline (still valid from above)
    lda SONG_PTN_CH0,x          ; A = pattern index for channel 0
    tay                         ; Y = pattern index (for table lookups)
    
    ; Load pattern length
    lda PATTERN_LEN,y           ; A = pattern length
    sta seq_ptn_len
    cmp seq_max_len             ; Update max if this is longer
    bcc @sls_no_max0            ; Branch if A < seq_max_len
    sta seq_max_len
@sls_no_max0:

    ; Load pattern pointer
    lda PATTERN_PTR_LO,y
    sta seq_ptn_start_lo        ; Pattern start (for wrap)
    sta seq_evt_ptr_lo          ; Current event pointer
    lda PATTERN_PTR_HI,y
    sta seq_ptn_start_hi
    sta seq_evt_ptr_hi
    
    ; Read first event's row number
    ; Y is clobbered by indirect load, but we're done with pattern index
    sta trk_ptr+1               ; A still has high byte
    lda seq_ptn_start_lo
    sta trk_ptr
    ldy #0
    lda (trk_ptr),y             ; First byte = row number of first event
    sta seq_evt_row             ; Store for channel 0
    
    ; =========================================================================
    ; Channel 1 Pattern Setup
    ; =========================================================================
    ldx seq_songline            ; Reload X (was clobbered by indirect load setup)
    lda SONG_PTN_CH1,x
    tay                         ; Y = pattern index
    
    lda PATTERN_LEN,y
    sta seq_ptn_len+1
    cmp seq_max_len
    bcc @sls_no_max1
    sta seq_max_len
@sls_no_max1:

    lda PATTERN_PTR_LO,y
    sta seq_ptn_start_lo+1
    sta seq_evt_ptr_lo+1
    lda PATTERN_PTR_HI,y
    sta seq_ptn_start_hi+1
    sta seq_evt_ptr_hi+1
    
    sta trk_ptr+1
    lda seq_ptn_start_lo+1
    sta trk_ptr
    ldy #0
    lda (trk_ptr),y
    sta seq_evt_row+1
    
    ; =========================================================================
    ; Channel 2 Pattern Setup
    ; =========================================================================
    ldx seq_songline            ; Reload X again
    lda SONG_PTN_CH2,x
    tay
    
    lda PATTERN_LEN,y
    sta seq_ptn_len+2
    cmp seq_max_len
    bcc @sls_no_max2
    sta seq_max_len
@sls_no_max2:

    lda PATTERN_PTR_LO,y
    sta seq_ptn_start_lo+2
    sta seq_evt_ptr_lo+2
    lda PATTERN_PTR_HI,y
    sta seq_ptn_start_hi+2
    sta seq_evt_ptr_hi+2
    
    sta trk_ptr+1
    lda seq_ptn_start_lo+2
    sta trk_ptr
    ldy #0
    lda (trk_ptr),y
    sta seq_evt_row+2
    
    ; =========================================================================
    ; Reset last instrument/volume for all channels
    ; =========================================================================
    ; New songline = fresh start, no inherited values from previous songline
    ldx #2                      ; Process channels 2, 1, 0
@sls_reset_last:
    lda #0
    sta seq_last_inst,x         ; Last instrument = 0
    lda #15
    sta seq_last_vol,x          ; Last volume = max (15)
    dex
    bpl @sls_reset_last         ; Loop while X >= 0
    
    rts
    ; Exit: A = 15, X = $FF, Y = 0
