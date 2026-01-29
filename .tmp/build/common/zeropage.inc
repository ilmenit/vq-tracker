; ==========================================================================
; ZERO PAGE DEFINITIONS
; ==========================================================================
; Memory layout for VQ sample playback and tracker sequencer.
;
; TRACKER mode uses $80-$BF for 3-channel polyphonic playback.
; Non-TRACKER mode uses simpler layout for single-channel players.
;
; ==========================================================================

.ifdef TRACKER

; ==========================================================================
; TRACKER MODE - 3-Channel Polyphonic Player
; ==========================================================================
; Uses $80-$BF range (64 bytes total)

    ; --- Channel 0 State ($80-$8C) ---
    trk0_stream_ptr   = $80     ; 2 bytes - Position in VQ index stream
    trk0_stream_end   = $82     ; 2 bytes - End of sample data
    trk0_sample_ptr   = $84     ; 2 bytes - Current VQ vector address
    trk0_vector_offset= $86     ; 1 byte  - Position within vector (0-15)
    trk0_pitch_frac   = $87     ; 1 byte  - Pitch accumulator fraction
    trk0_pitch_int    = $88     ; 1 byte  - Pitch accumulator integer
    trk0_pitch_step   = $89     ; 2 bytes - 8.8 fixed-point pitch step
    trk0_active       = $8B     ; 1 byte  - $FF=active, $00=inactive
    trk0_note         = $8C     ; 1 byte  - Current note (for debug)
    
    ; --- Sequencer Core State ($8D-$8F) ---
    seq_row           = $8D     ; 1 byte  - Current row (0-254)
    seq_tick          = $8E     ; 1 byte  - Tick counter (0 to speed-1)
    seq_playing       = $8F     ; 1 byte  - $FF=playing, $00=stopped

    ; --- Channel 1 State ($90-$9C) ---
    trk1_stream_ptr   = $90     ; 2 bytes
    trk1_stream_end   = $92     ; 2 bytes
    trk1_sample_ptr   = $94     ; 2 bytes
    trk1_vector_offset= $96     ; 1 byte
    trk1_pitch_frac   = $97     ; 1 byte
    trk1_pitch_int    = $98     ; 1 byte
    trk1_pitch_step   = $99     ; 2 bytes
    trk1_active       = $9B     ; 1 byte
    trk1_note         = $9C     ; 1 byte
    
    ; --- Sequencer Extended ($9D-$9F) ---
    seq_songline      = $9D     ; 1 byte  - Current songline (0-255)
    parse_temp        = $9E     ; 1 byte  - Temp for event parsing
    parse_channel     = $9F     ; 1 byte  - Channel being parsed
    
    ; --- Channel 2 State ($A0-$AC) ---
    trk2_stream_ptr   = $A0     ; 2 bytes
    trk2_stream_end   = $A2     ; 2 bytes
    trk2_sample_ptr   = $A4     ; 2 bytes
    trk2_vector_offset= $A6     ; 1 byte
    trk2_pitch_frac   = $A7     ; 1 byte
    trk2_pitch_int    = $A8     ; 1 byte
    trk2_pitch_step   = $A9     ; 2 bytes
    trk2_active       = $AB     ; 1 byte
    trk2_note         = $AC     ; 1 byte
    
    ; --- Sequencer Config ($AD-$AF) ---
    seq_speed         = $AD     ; 1 byte  - VBLANKs per row (1-255)
    seq_max_len       = $AE     ; 1 byte  - Max pattern length
    last_key_state    = $AF     ; 1 byte  - Keyboard debounce

    ; --- Temporary/Common ($B0-$BF) ---
    chn_idx           = $B0     ; 1 byte  - Current channel index
    last_key_code     = $B1     ; 1 byte  - Last key code ($FF=none)
    trk_ptr           = $B2     ; 2 bytes - IRQ temp pointer
    ; $B4 reserved
    sample_ptr        = $B5     ; 2 bytes - General sample pointer
    nibble_state      = $B7     ; 1 byte  - Nibble toggle (pokey_setup)
    
    .ifndef USE_STACK_IRQ
    irq_save_a        = $B8     ; 1 byte  - IRQ register save
    irq_save_x        = $B9     ; 1 byte
    irq_save_y        = $BA     ; 1 byte
    .endif
    
    trk_overflow      = $BB     ; 1 byte  - Pitch overflow flag
    seq_ptr           = $BC     ; 2 bytes - NMI temp pointer (separate from IRQ)
    
    ; --- Volume Control (when VOLUME_CONTROL=1) ---
    ; These are pre-shifted to high nibble: volume * 16
    ; Used as index into VOLUME_SCALE LUT: LUT[sample + vol_shifted]
    trk0_vol_shift    = $BE     ; 1 byte  - Channel 0 volume (<<4)
    trk1_vol_shift    = $BF     ; 1 byte  - Channel 1 volume (<<4)
    
; NOTE: Channel 2 volume stored in regular memory (out of ZP space)
; See song_player.asm for trk2_vol_shift location

.else

; ==========================================================================
; NON-TRACKER MODE - Simple Single-Channel Players
; ==========================================================================

    ; --- Core Playback ---
    stream_ptr      = $80       ; 2 bytes - VQ index stream position
    stream_end      = $82       ; 2 bytes - End address for loop
    sample_ptr      = $8A       ; 2 bytes - Current sample data
    sample_len      = $8C       ; 1 byte  - Samples in current vector

    ; --- IRQ Context ---
    .ifndef USE_STACK_IRQ
    irq_save_a      = $8D       ; 1 byte
    irq_save_x      = $8E       ; 1 byte
    irq_save_y      = $8F       ; 1 byte
    .endif

    ; --- Sliding Window Mode ---
    ptr_lens        = $84       ; 2 bytes - VQ_LENS table pointer
    ptr_lo          = $86       ; 2 bytes - VQ_LO table pointer
    ptr_hi          = $88       ; 2 bytes - VQ_HI table pointer
    slide_counter_lo = $90      ; 1 byte  - Slide counter (lo)
    slide_counter_hi = $91      ; 1 byte  - Slide counter (hi)

    ; --- Single Channel Mode ---
    nibble_state    = $92       ; 1 byte  - Nibble toggle (0=lo, 1=hi)

    ; --- Multi-Sample Mode ---
    sample_finished = $93       ; 1 byte  - $FF when done
    current_sample  = $94       ; 1 byte  - Playing sample index

    ; --- Pitch Control ---
    pitch_step      = $95       ; 2 bytes - 8.8 fixed-point step
    pitch_frac      = $97       ; 1 byte  - Fractional accumulator
    pitch_int       = $98       ; 1 byte  - Integer samples to advance
    pitch_save_x    = $99       ; 1 byte  - Temp save

.endif

; ==========================================================================
; END OF ZERO PAGE DEFINITIONS
; ==========================================================================
