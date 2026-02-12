; ==========================================================================
; SEQ_LOAD_SONGLINE.ASM - Load Songline Configuration (4-channel)
; ==========================================================================

seq_load_songline:
    ldx seq_songline            ; X = songline index

    ; Load songline speed
    lda SONG_SPEED,x
    sta seq_speed

    ; Reset row counters
    lda #0
    sta seq_row
    sta seq_max_len
    sta seq_local_row
    sta seq_local_row+1
    sta seq_local_row+2
    sta seq_local_row+3

    ; =========================================================================
    ; Channel 0 Pattern Setup
    ; =========================================================================
    lda SONG_PTN_CH0,x
    tay

    lda PATTERN_LEN,y
    sta seq_ptn_len
    cmp seq_max_len
    bcc @sls_no_max0
    sta seq_max_len
@sls_no_max0:

    lda PATTERN_PTR_LO,y
    sta seq_ptn_start_lo
    sta seq_evt_ptr_lo
    lda PATTERN_PTR_HI,y
    sta seq_ptn_start_hi
    sta seq_evt_ptr_hi

    sta trk_ptr+1
    lda seq_ptn_start_lo
    sta trk_ptr
    ldy #0
    lda (trk_ptr),y
    sta seq_evt_row

    ; =========================================================================
    ; Channel 1 Pattern Setup
    ; =========================================================================
    ldx seq_songline
    lda SONG_PTN_CH1,x
    tay

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
    ldx seq_songline
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
    ; Channel 3 Pattern Setup
    ; =========================================================================
    ldx seq_songline
    lda SONG_PTN_CH3,x
    tay

    lda PATTERN_LEN,y
    sta seq_ptn_len+3
    cmp seq_max_len
    bcc @sls_no_max3
    sta seq_max_len
@sls_no_max3:

    lda PATTERN_PTR_LO,y
    sta seq_ptn_start_lo+3
    sta seq_evt_ptr_lo+3
    lda PATTERN_PTR_HI,y
    sta seq_ptn_start_hi+3
    sta seq_evt_ptr_hi+3

    sta trk_ptr+1
    lda seq_ptn_start_lo+3
    sta trk_ptr
    ldy #0
    lda (trk_ptr),y
    sta seq_evt_row+3

    ; =========================================================================
    ; Reset last instrument/volume for all channels
    ; =========================================================================
    ldx #3
@sls_reset_last:
    lda #0
    sta seq_last_inst,x
    lda #15
    sta seq_last_vol,x
    dex
    bpl @sls_reset_last

    rts
