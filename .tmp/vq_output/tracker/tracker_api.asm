; ==========================================================================
; TRACKER API - FIXED VERSION
; ==========================================================================
; This module handles the "Note On" logic for the polyphonic tracker.
;
; Responsibilities:
; 1. Select target hardware channel (0, 1, or 2)
; 2. Initialize pitch variables (step size based on note)
; 3. Set up sample stream pointers
; 4. Pre-load VQ cache for immediate playback
;
; FIXES APPLIED:
; - Sample index preserved correctly (was being destroyed)
; - Initial vector offset set to 0
; - Cache pre-load stores vector BASE address (IRQ handles nibble offset)
; ==========================================================================

; Tracker_PlayNote: 
; Implements "Note On" event for a specific channel.
;
; Inputs:
;   A = Sample Index (0 to SAMPLE_COUNT-1)
;   X = Note Index (0-47)
;   Y = Channel Index (0-2)
;
; Modifies: A, X, Y, trk_ptr
;
Tracker_PlayNote:
    ; Bounds check sample index
    cmp #SAMPLE_COUNT
    bcc @sample_ok
    rts                     ; Invalid sample, do nothing
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
    ; Save sample index before we use A for other things
    pha
    
    ; Deactivate channel during setup (prevents IRQ race condition)
    lda #0
    sta trk0_active
    
    ; Store note for reference
    stx trk0_note
    
    ; 1. Setup Pitch Stepping (8.8 fixed point)
    lda NOTE_PITCH_LO,x
    sta trk0_pitch_step
    lda NOTE_PITCH_HI,x
    sta trk0_pitch_step+1
    
    ; Reset pitch accumulator
    lda #0
    sta trk0_pitch_frac
    sta trk0_pitch_int
    sta trk0_vector_offset  ; Start at sample 0 within vector
    
    ; 2. Setup Sample Stream Pointers
    pla                     ; Restore sample index
    tax                     ; X = sample index
    
    lda SAMPLE_START_LO,x
    sta trk0_stream_ptr
    lda SAMPLE_START_HI,x
    sta trk0_stream_ptr+1
    lda SAMPLE_END_LO,x
    sta trk0_stream_end
    lda SAMPLE_END_HI,x
    sta trk0_stream_end+1
    
    ; 3. Pre-load VQ Cache
    ; Fetch initial codebook index from stream
    lda trk0_stream_ptr
    sta trk_ptr
    lda trk0_stream_ptr+1
    sta trk_ptr+1
    
    ldy #0
    lda (trk_ptr),y         ; A = VQ codebook index
    tay                     ; Y = VQ index
    
    ; Store BASE address of vector (IRQ will add nibble offset)
    lda VQ_LO,y
    sta trk0_sample_ptr
    lda VQ_HI,y
    sta trk0_sample_ptr+1
    
    ; 4. Activate Channel
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
    
    ; Setup Pitch
    lda NOTE_PITCH_LO,x
    sta trk1_pitch_step
    lda NOTE_PITCH_HI,x
    sta trk1_pitch_step+1
    
    lda #0
    sta trk1_pitch_frac
    sta trk1_pitch_int
    sta trk1_vector_offset
    
    ; Setup Stream Pointers
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
    
    ; Pre-load Cache
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
    
    ; Setup Pitch
    lda NOTE_PITCH_LO,x
    sta trk2_pitch_step
    lda NOTE_PITCH_HI,x
    sta trk2_pitch_step+1
    
    lda #0
    sta trk2_pitch_frac
    sta trk2_pitch_int
    sta trk2_vector_offset
    
    ; Setup Stream Pointers
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
    
    ; Pre-load Cache
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
