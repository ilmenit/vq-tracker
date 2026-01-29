; ==========================================================================
; TRACKER API - Note Trigger Module
; ==========================================================================
; Handles "Note On" events for the 3-channel polyphonic tracker.
;
; Entry Point:
;   Tracker_PlayNote - Start playing a note on a channel
;
; Responsibilities:
;   1. Select target hardware channel (0, 1, or 2)
;   2. Initialize pitch variables (8.8 fixed-point step from note index)
;   3. Set up sample stream pointers from SAMPLE_DIR
;   4. Pre-load VQ cache for immediate playback
;
; Register Usage:
;   A = Sample Index (0 to SAMPLE_COUNT-1)
;   X = Note Index (0-35: C-1=0, C-2=12, C-3=24)
;   Y = Channel Index (0-2)
;
; ==========================================================================

Tracker_PlayNote:
    ; Bounds check sample index
    cmp #SAMPLE_COUNT
    bcc @sample_ok
    rts                         ; Invalid sample, abort
@sample_ok:

    ; Dispatch to channel handler
    cpy #0
    beq @set_ch0
    cpy #1
    beq @set_ch1
    jmp @set_ch2

; =========================================================================
; CHANNEL 0 SETUP
; =========================================================================
@set_ch0:
    pha                         ; Save sample index
    
    ; Deactivate during setup (prevent IRQ race)
    lda #0
    sta trk0_active
    
    ; Store note for debug/display
    stx trk0_note
    
    ; Setup pitch step from note index (8.8 fixed point)
    lda NOTE_PITCH_LO,x
    sta trk0_pitch_step
    lda NOTE_PITCH_HI,x
    sta trk0_pitch_step+1
    
    ; Reset pitch accumulator
    lda #0
    sta trk0_pitch_frac
    sta trk0_pitch_int
    sta trk0_vector_offset      ; Start at sample 0 within vector
    
    ; Setup sample stream pointers
    pla                         ; Restore sample index
    tax
    
    lda SAMPLE_START_LO,x
    sta trk0_stream_ptr
    lda SAMPLE_START_HI,x
    sta trk0_stream_ptr+1
    lda SAMPLE_END_LO,x
    sta trk0_stream_end
    lda SAMPLE_END_HI,x
    sta trk0_stream_end+1
    
    ; Pre-load VQ cache (first codebook entry)
    lda trk0_stream_ptr
    sta trk_ptr
    lda trk0_stream_ptr+1
    sta trk_ptr+1
    
    ldy #0
    lda (trk_ptr),y             ; Get first VQ index
    tay
    
    lda VQ_LO,y
    sta trk0_sample_ptr
    lda VQ_HI,y
    sta trk0_sample_ptr+1
    
    ; Activate channel
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
    
    lda #$FF
    sta trk2_active
    rts
