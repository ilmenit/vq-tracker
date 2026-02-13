; ==========================================================================
; TRACKER API - Note Trigger Module (4-channel)
; ==========================================================================
; Entry Point:
;   Tracker_PlayNote - Start playing a note on a channel
;
; Register Usage:
;   A = Sample Index (0 to SAMPLE_COUNT-1)
;   X = Note Index (0-59: see pitch_tables.asm for extended 5-octave range)
;   Y = Channel Index (0-3)
; ==========================================================================

Tracker_PlayNote:
    ; Bounds check sample index
    cmp #SAMPLE_COUNT
    bcc @sample_ok
    rts
@sample_ok:

    ; Dispatch to channel handler
    cpy #0
    beq @set_ch0
    cpy #1
    beq @set_ch1
    cpy #2
    beq @set_ch2
    jmp @set_ch3

; =========================================================================
; CHANNEL 0 SETUP
; =========================================================================
@set_ch0:
    pha
    
    lda #0
    sta trk0_active
    stx trk0_note
    
    lda NOTE_PITCH_LO,x
    sta trk0_pitch_step
    lda NOTE_PITCH_HI,x
    sta trk0_pitch_step+1
    
.if VOLUME_CONTROL = 1
    lda #<ch0_vq_pitch
    sta ch0_tick_jmp
    lda #>ch0_vq_pitch
    sta ch0_tick_jmp+1
.else
    lda trk0_pitch_step+1
    cmp #$01
    bne @ch0_api_pitch
    lda trk0_pitch_step
    bne @ch0_api_pitch
    ; No pitch: step = 1.0
    lda #<ch0_vq_no_pitch
    ldx #>ch0_vq_no_pitch
    jmp @ch0_api_set_dispatch
@ch0_api_pitch:
    lda #<ch0_vq_pitch
    ldx #>ch0_vq_pitch
@ch0_api_set_dispatch:
    sta ch0_tick_jmp
    stx ch0_tick_jmp+1
.endif
    
    lda #0
    sta trk0_pitch_frac
    sta trk0_pitch_int
    sta trk0_vector_offset
    
    pla
    tax
    
    lda SAMPLE_START_LO,x
    sta trk0_stream_ptr
    lda SAMPLE_START_HI,x
    sta trk0_stream_ptr+1
    lda SAMPLE_END_LO,x
    sta trk0_stream_end
    lda SAMPLE_END_HI,x
    sta trk0_stream_end+1
    
    lda trk0_stream_ptr
    sta trk_ptr
    lda trk0_stream_ptr+1
    sta trk_ptr+1
    
    ldy #0
    lda (trk_ptr),y
    tay
    
    lda VQ_LO,y
    sta trk0_sample_ptr
    lda VQ_HI,y
    sta trk0_sample_ptr+1
    
    ; tick_jmp already set above (VQ mode only in API)
    
    lda #$FF
    sta trk0_active
    rts

; =========================================================================
; CHANNEL 1 SETUP
; =========================================================================
@set_ch1:
    pha
    
    lda #0
    sta trk1_active
    stx trk1_note
    
    lda NOTE_PITCH_LO,x
    sta trk1_pitch_step
    lda NOTE_PITCH_HI,x
    sta trk1_pitch_step+1
    
.if VOLUME_CONTROL = 1
    lda #<ch1_vq_pitch
    sta ch1_tick_jmp
    lda #>ch1_vq_pitch
    sta ch1_tick_jmp+1
.else
    lda trk1_pitch_step+1
    cmp #$01
    bne @ch1_api_pitch
    lda trk1_pitch_step
    bne @ch1_api_pitch
    ; No pitch: step = 1.0
    lda #<ch1_vq_no_pitch
    ldx #>ch1_vq_no_pitch
    jmp @ch1_api_set_dispatch
@ch1_api_pitch:
    lda #<ch1_vq_pitch
    ldx #>ch1_vq_pitch
@ch1_api_set_dispatch:
    sta ch1_tick_jmp
    stx ch1_tick_jmp+1
.endif
    
    lda #0
    sta trk1_pitch_frac
    sta trk1_pitch_int
    sta trk1_vector_offset
    
    pla
    tax
    
    lda SAMPLE_START_LO,x
    sta trk1_stream_ptr
    lda SAMPLE_START_HI,x
    sta trk1_stream_ptr+1
    lda SAMPLE_END_LO,x
    sta trk1_stream_end
    lda SAMPLE_END_HI,x
    sta trk1_stream_end+1
    
    lda trk1_stream_ptr
    sta trk_ptr
    lda trk1_stream_ptr+1
    sta trk_ptr+1
    
    ldy #0
    lda (trk_ptr),y
    tay
    
    lda VQ_LO,y
    sta trk1_sample_ptr
    lda VQ_HI,y
    sta trk1_sample_ptr+1
    
    ; tick_jmp already set above (VQ mode only in API)
    
    lda #$FF
    sta trk1_active
    rts

; =========================================================================
; CHANNEL 2 SETUP
; =========================================================================
@set_ch2:
    pha
    
    lda #0
    sta trk2_active
    stx trk2_note
    
    lda NOTE_PITCH_LO,x
    sta trk2_pitch_step
    lda NOTE_PITCH_HI,x
    sta trk2_pitch_step+1
    
.if VOLUME_CONTROL = 1
    lda #<ch2_vq_pitch
    sta ch2_tick_jmp
    lda #>ch2_vq_pitch
    sta ch2_tick_jmp+1
.else
    lda trk2_pitch_step+1
    cmp #$01
    bne @ch2_api_pitch
    lda trk2_pitch_step
    bne @ch2_api_pitch
    ; No pitch: step = 1.0
    lda #<ch2_vq_no_pitch
    ldx #>ch2_vq_no_pitch
    jmp @ch2_api_set_dispatch
@ch2_api_pitch:
    lda #<ch2_vq_pitch
    ldx #>ch2_vq_pitch
@ch2_api_set_dispatch:
    sta ch2_tick_jmp
    stx ch2_tick_jmp+1
.endif
    
    lda #0
    sta trk2_pitch_frac
    sta trk2_pitch_int
    sta trk2_vector_offset
    
    pla
    tax
    
    lda SAMPLE_START_LO,x
    sta trk2_stream_ptr
    lda SAMPLE_START_HI,x
    sta trk2_stream_ptr+1
    lda SAMPLE_END_LO,x
    sta trk2_stream_end
    lda SAMPLE_END_HI,x
    sta trk2_stream_end+1
    
    lda trk2_stream_ptr
    sta trk_ptr
    lda trk2_stream_ptr+1
    sta trk_ptr+1
    
    ldy #0
    lda (trk_ptr),y
    tay
    
    lda VQ_LO,y
    sta trk2_sample_ptr
    lda VQ_HI,y
    sta trk2_sample_ptr+1
    
    ; tick_jmp already set above (VQ mode only in API)
    
    lda #$FF
    sta trk2_active
    rts

; =========================================================================
; CHANNEL 3 SETUP
; =========================================================================
@set_ch3:
    pha
    
    lda #0
    sta trk3_active
    stx trk3_note
    
    lda NOTE_PITCH_LO,x
    sta trk3_pitch_step
    lda NOTE_PITCH_HI,x
    sta trk3_pitch_step+1
    
.if VOLUME_CONTROL = 1
    lda #<ch3_vq_pitch
    sta ch3_tick_jmp
    lda #>ch3_vq_pitch
    sta ch3_tick_jmp+1
.else
    lda trk3_pitch_step+1
    cmp #$01
    bne @ch3_api_pitch
    lda trk3_pitch_step
    bne @ch3_api_pitch
    ; No pitch: step = 1.0
    lda #<ch3_vq_no_pitch
    ldx #>ch3_vq_no_pitch
    jmp @ch3_api_set_dispatch
@ch3_api_pitch:
    lda #<ch3_vq_pitch
    ldx #>ch3_vq_pitch
@ch3_api_set_dispatch:
    sta ch3_tick_jmp
    stx ch3_tick_jmp+1
.endif
    
    lda #0
    sta trk3_pitch_frac
    sta trk3_pitch_int
    sta trk3_vector_offset
    
    pla
    tax
    
    lda SAMPLE_START_LO,x
    sta trk3_stream_ptr
    lda SAMPLE_START_HI,x
    sta trk3_stream_ptr+1
    lda SAMPLE_END_LO,x
    sta trk3_stream_end
    lda SAMPLE_END_HI,x
    sta trk3_stream_end+1
    
    lda trk3_stream_ptr
    sta trk_ptr
    lda trk3_stream_ptr+1
    sta trk_ptr+1
    
    ldy #0
    lda (trk_ptr),y
    tay
    
    lda VQ_LO,y
    sta trk3_sample_ptr
    lda VQ_HI,y
    sta trk3_sample_ptr+1
    
    ; tick_jmp already set above (VQ mode only in API)
    
    lda #$FF
    sta trk3_active
    rts
