; ==========================================================================
; TRACKER API - Note Trigger Module (4-channel)
; ==========================================================================
; Entry Point:
;   Tracker_PlayNote - Start playing a note on a channel
;
; Register Usage:
;   A = Sample Index (0 to SAMPLE_COUNT-1)
;   X = Note Index (0-59: see pitch_tables.asm for 5-octave range)
;   Y = Channel Index (0-3)
; ==========================================================================

; ==========================================================================
; PLAY_NOTE_CHANNEL — Setup one channel for playback
; ==========================================================================
; :1 = channel (0-3)
; Assumes: sample index on stack, note index in X register
; ==========================================================================
.macro PLAY_NOTE_CHANNEL
    pha

    lda #0
    sta trk:1_active
    stx trk:1_note

    lda NOTE_PITCH_LO,x
    sta trk:1_pitch_step
    lda NOTE_PITCH_HI,x
    sta trk:1_pitch_step+1

.if VOLUME_CONTROL = 1
    ; Volume control always uses pitch path
    lda #<ch:1_vq_pitch
    sta ch:1_tick_jmp
    lda #>ch:1_vq_pitch
    sta ch:1_tick_jmp+1
.else
    lda trk:1_pitch_step+1
    cmp #$01
    bne @api_pitch_:1
    lda trk:1_pitch_step
    bne @api_pitch_:1
    ; No pitch: step = 1.0
    lda #<ch:1_vq_no_pitch
    ldx #>ch:1_vq_no_pitch
    jmp @api_set_:1
@api_pitch_:1:
    lda #<ch:1_vq_pitch
    ldx #>ch:1_vq_pitch
@api_set_:1:
    sta ch:1_tick_jmp
    stx ch:1_tick_jmp+1
.endif

    lda #0
    sta trk:1_pitch_frac
    sta trk:1_pitch_int
    sta trk:1_vector_offset

    pla
    tax

    lda SAMPLE_START_LO,x
    sta trk:1_stream_ptr
    lda SAMPLE_START_HI,x
    sta trk:1_stream_ptr+1
    lda SAMPLE_END_LO,x
    sta trk:1_stream_end
    lda SAMPLE_END_HI,x
    sta trk:1_stream_end+1

    lda trk:1_stream_ptr
    sta trk_ptr
    lda trk:1_stream_ptr+1
    sta trk_ptr+1

    ldy #0
    lda (trk_ptr),y
    tay
    lda VQ_LO,y
    sta trk:1_sample_ptr
    lda VQ_HI,y
    sta trk:1_sample_ptr+1

    lda #$FF
    sta trk:1_active
    rts
.endm


Tracker_PlayNote:
    ; Bounds check
    cmp #SAMPLE_COUNT
    bcc @sample_ok
    rts
@sample_ok:
    ; Dispatch to channel
    cpy #0
    beq @set_ch0
    cpy #1
    beq @set_ch1
    cpy #2
    beq @set_ch2
    jmp @set_ch3

@set_ch0:
    PLAY_NOTE_CHANNEL 0
@set_ch1:
    PLAY_NOTE_CHANNEL 1
@set_ch2:
    PLAY_NOTE_CHANNEL 2
@set_ch3:
    PLAY_NOTE_CHANNEL 3
