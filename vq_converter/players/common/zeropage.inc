; =============================================================================
; ZERO PAGE DEFINITIONS
; =============================================================================
; Memory map for VQ players and tracker
; =============================================================================

; -----------------------------------------------------------------------------
; TRACKER PLAYER (Structure of Arrays)
; -----------------------------------------------------------------------------
.ifdef TRACKER
    ; We use $80-$BF range for tracker mode
    
    ; --- POLYPHONIC TRACKER OPTIMIZED LAYOUT ---
    ; Channel 0 ($80-$8F)
    trk0_stream_ptr   = $80 ; 2 bytes - Current position in VQ index stream
    trk0_stream_end   = $82 ; 2 bytes - End of sample data
    trk0_sample_ptr   = $84 ; 2 bytes - Current VQ vector address
    trk0_vector_offset= $86 ; 1 byte  - Position within current vector
    trk0_pitch_frac   = $87 ; 1 byte  - Pitch accumulator fractional part
    trk0_pitch_int    = $88 ; 1 byte  - Pitch accumulator integer part
    trk0_pitch_step   = $89 ; 2 bytes - 8.8 fixed-point pitch increment
    trk0_active       = $8B ; 1 byte  - Channel active flag ($FF=active)
    trk0_note         = $8C ; 1 byte  - Current note (Debug/UI)

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
    
    ; Channel 2 ($A0-$AF)
    trk2_stream_ptr   = $A0 ; 2 bytes
    trk2_stream_end   = $A2 ; 2 bytes
    trk2_sample_ptr   = $A4 ; 2 bytes
    trk2_vector_offset= $A6 ; 1 byte
    trk2_pitch_frac   = $A7 ; 1 byte
    trk2_pitch_int    = $A8 ; 1 byte
    trk2_pitch_step   = $A9 ; 2 bytes
    trk2_active       = $AB ; 1 byte
    trk2_note         = $AC ; 1 byte

    ; --- Temp / Common ($B0-$BF) ---
    chn_idx           = $B0 ; 1 byte  - Current channel index
    ; $B1 reserved
    trk_ptr           = $B2 ; 2 bytes - IRQ temp pointer (VQ lookups)
    ; $B4 reserved
    sample_ptr        = $B5 ; 2 bytes - Sample data pointer
    nibble_state      = $B7 ; 1 byte  - Nibble toggle (required by pokey_setup)
    
    .ifndef USE_STACK_IRQ
    irq_save_a        = $B8 ; 1 byte  - IRQ register save
    irq_save_x        = $B9 ; 1 byte
    irq_save_y        = $BA ; 1 byte
    .endif
    
    trk_overflow      = $BB ; 1 byte  - Overflow flag for pitch calculations
    
    ; --- Song Player Sequencer ($BC-$BF) ---
    ; IMPORTANT: seq_ptr MUST be separate from trk_ptr!
    ; NMI (sequencer) and IRQ (sample playback) can interrupt each other.
    ; If they share a pointer, data corruption occurs.
    seq_ptr           = $BC ; 2 bytes - NMI temp pointer (pattern data)
    ; $BE-$BF reserved for future use

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
