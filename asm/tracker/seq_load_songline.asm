; ==========================================================================
; SEQ_LOAD_SONGLINE.ASM - Load Songline Configuration (4-channel)
; ==========================================================================

; ==========================================================================
; LOAD_CHANNEL_PTN — Load one channel's pattern from songline
; ==========================================================================
; :1 = channel (0-3)
; :2 = SONG_PTN_CHx table
; ==========================================================================
.macro LOAD_CHANNEL_PTN
    ldx seq_songline
    lda :2,x
    tay

    lda PATTERN_LEN,y
    sta seq_ptn_len+:1
    cmp seq_max_len
    bcc @+
    sta seq_max_len
@
    lda PATTERN_PTR_LO,y
    sta seq_ptn_start_lo+:1
    sta seq_evt_ptr_lo+:1
    lda PATTERN_PTR_HI,y
    sta seq_ptn_start_hi+:1
    sta seq_evt_ptr_hi+:1

    sta trk_ptr+1
    lda seq_ptn_start_lo+:1
    sta trk_ptr
    ldy #0
    lda (trk_ptr),y
    sta seq_evt_row+:1
.endm

seq_load_songline:
    ldx seq_songline
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

    LOAD_CHANNEL_PTN 0, SONG_PTN_CH0
    LOAD_CHANNEL_PTN 1, SONG_PTN_CH1
    LOAD_CHANNEL_PTN 2, SONG_PTN_CH2
    LOAD_CHANNEL_PTN 3, SONG_PTN_CH3

    ; Reset last instrument/volume
    ldx #3
@sls_reset_last:
    lda #0
    sta seq_last_inst,x
    lda #15
    sta seq_last_vol,x
    dex
    bpl @sls_reset_last

    rts
