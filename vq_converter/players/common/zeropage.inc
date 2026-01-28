
; -----------------------------------------------------------------------------
; TRACKER PLAYER (Structure of Arrays)
; -----------------------------------------------------------------------------
.ifdef TRACKER
    ; We use $80-$AF range (+ some overlap potentially, total 27 bytes used here)
    ; --- POLYPHONIC TRACKER OPTIMIZED LAYOUT ---
    ; Channel 0 ($80-$8F)
    trk0_stream_ptr   = $80 ; 2 bytes
    trk0_stream_end   = $82 ; 2 bytes
    trk0_sample_ptr   = $84 ; 2 bytes
    trk0_vector_offset= $86 ; 1 byte
    trk0_pitch_frac   = $87 ; 1 byte
    trk0_pitch_int    = $88 ; 1 byte
    trk0_pitch_step   = $89 ; 2 bytes
    trk0_active       = $8B ; 1 byte
    trk0_note         = $8C ; 1 byte (Debug/UI)

    ; Channel 1 ($90-$9F)
    trk1_stream_ptr   = $90 ; 2 bytes
    trk1_stream_end   = $92 ; 2 bytes
    trk1_sample_ptr   = $94 ; 2 bytes
    trk1_vector_offset= $96 ; 1 byte
    trk1_pitch_frac   = $97 ; 1 byte
    trk1_pitch_int    = $98 ; 1 byte
    trk1_pitch_step   = $99 ; 2 bytes
    trk1_active       = $9B ; 1 byte
    trk1_note         = $9C ; 1 byte
    
    ; Channel 2 ($A0-$AF) - Reusing some space? 
    ; We have space up to $B0 safely.
    trk2_stream_ptr   = $A0 ; 2 bytes
    trk2_stream_end   = $A2 ; 2 bytes
    trk2_sample_ptr   = $A4 ; 2 bytes
    trk2_vector_offset= $A6 ; 1 byte
    trk2_pitch_frac   = $A7 ; 1 byte
    trk2_pitch_int    = $A8 ; 1 byte
    trk2_pitch_step   = $A9 ; 2 bytes
    trk2_active       = $AB ; 1 byte
    trk2_note         = $AC ; 1 byte

    ; Temp / Common ($B0+)
    chn_idx           = $B0
    trk_ptr           = $B2 ; 2 bytes

    ; Common vars needed by Tracker (mapped to free space after arrays)
    sample_ptr        = $B5 ; 2 bytes
    nibble_state      = $B7 ; 1 byte (Required by pokey_setup)
    trk_overflow      = $BB ; FIX ASM-5: Overflow flag for pitch calculations
    
    .ifndef USE_STACK_IRQ
    irq_save_a        = $B8
    irq_save_x        = $B9
    irq_save_y        = $BA
    .endif

.else
    ; -----------------------------------------------------------------------------
    ; CORE PLAYBACK (All Modes: RAW, FIXED, SLIDING)
    ; -----------------------------------------------------------------------------
    sample_ptr      = $8A       ; 2 bytes - Pointer to current sample data
    sample_len      = $8C       ; 1 byte  - Samples remaining in current vector

    ; -----------------------------------------------------------------------------
    ; STREAM CONTROL (All Modes)
    ; -----------------------------------------------------------------------------
    stream_ptr      = $80       ; 2 bytes - Pointer to stream index data (VQ modes)
    stream_end      = $82       ; 2 bytes - End address for loop detection

    ; -----------------------------------------------------------------------------
    ; IRQ CONTEXT SAVE (All Modes)
    ; -----------------------------------------------------------------------------
    .ifndef USE_STACK_IRQ
    irq_save_a      = $8D       ; 1 byte  - Accumulator save during IRQ
    irq_save_x      = $8E       ; 1 byte  - X register save during IRQ
    irq_save_y      = $8F       ; 1 byte  - Y register save during IRQ
    .endif

    ; -----------------------------------------------------------------------------
    ; SLIDING WINDOW (ALGO_SLIDING only)
    ; -----------------------------------------------------------------------------
    ptr_lens        = $84       ; 2 bytes - Pointer to VQ_LENS table (sliding)
    ptr_lo          = $86       ; 2 bytes - Pointer to VQ_LO table (sliding)
    ptr_hi          = $88       ; 2 bytes - Pointer to VQ_HI table (sliding)
    slide_counter_lo = $90      ; 1 byte  - Slide interval counter (low byte)
    slide_counter_hi = $91      ; 1 byte  - Slide interval counter (high byte)

    ; -----------------------------------------------------------------------------
    ; SINGLE CHANNEL MODE (CHANNELS = 1)
    ; -----------------------------------------------------------------------------
    nibble_state    = $92       ; 1 byte  - Nibble toggle: 0=low, 1=high

    ; -----------------------------------------------------------------------------
    ; MULTI-SAMPLE MODE (MULTI_SAMPLE defined)
    ; -----------------------------------------------------------------------------
    sample_finished = $93       ; 1 byte  - $FF when sample finished, $00 otherwise
    current_sample  = $94       ; 1 byte  - Currently playing sample index ($FF = none)

    ; -----------------------------------------------------------------------------
    ; PITCH CONTROL (PITCH_CONTROL defined)
    ; -----------------------------------------------------------------------------
    pitch_step      = $95       ; 2 bytes - 8.8 fixed-point pitch step (lo/hi)
    pitch_frac      = $97       ; 1 byte  - Fractional accumulator
    pitch_int       = $98       ; 1 byte  - Integer samples to advance this IRQ
    pitch_save_x    = $99       ; 1 byte  - Temp save for loop counter
.endif

; =============================================================================
; END OF ZERO PAGE DEFINITIONS
; =============================================================================
