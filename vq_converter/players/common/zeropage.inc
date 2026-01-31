; ==========================================================================
; ZERO PAGE DEFINITIONS
; ==========================================================================
; Memory layout for VQ sample playback and tracker sequencer.
;
; =========================================================================
; CRITICAL: IRQ/NMI RACE CONDITION PREVENTION
; =========================================================================
; NMI (Non-Maskable Interrupt) can fire at ANY time - even during IRQ!
; The I flag (set automatically during IRQ) does NOT block NMI.
;
; Therefore IRQ and NMI MUST use COMPLETELY SEPARATE temp variables:
;
;   IRQ-ONLY ($B2-$B4):
;     irq_ptr     - Temp pointer for VQ vector loading in IRQ handler
;     irq_busy    - Flag: $FF while IRQ is running (NMI can check this)
;
;   NMI-ONLY ($BC-$BD):  
;     trk_ptr     - Temp pointer for tracker_api.asm (note triggers)
;
; If these were shared, NMI could corrupt IRQ's pointer mid-operation,
; causing garbage audio output, crashes, or register corruption.
;
; TRACKER mode uses $80-$C2 for 3-channel polyphonic playback.
; Non-TRACKER mode uses simpler layout for single-channel players.
; =========================================================================

.ifdef TRACKER

; ==========================================================================
; TRACKER MODE - 3-Channel Polyphonic Player
; ==========================================================================

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
    parse_temp        = $9E     ; 1 byte  - Temp for event parsing (NMI context)
    parse_channel     = $9F     ; 1 byte  - Channel being parsed (NMI context)
    
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

    ; =========================================================================
    ; IRQ-ONLY VARIABLES ($B0-$BA)
    ; =========================================================================
    ; Used EXCLUSIVELY by IRQ handler. NMI must NEVER write to these!
    ; (NMI may read irq_busy to check if IRQ is active)
    
    chn_idx           = $B0     ; 1 byte  - Current channel index
    last_key_code     = $B1     ; 1 byte  - Last key code ($FF=none)
    irq_ptr           = $B2     ; 2 bytes - IRQ-ONLY temp pointer *** CRITICAL ***
    irq_busy          = $B4     ; 1 byte  - $FF=IRQ running, $00=idle
    sample_ptr        = $B5     ; 2 bytes - General sample pointer  
    nibble_state      = $B7     ; 1 byte  - Nibble toggle (pokey_setup)
    
    ; IRQ Register Saves - zero-page is faster than stack
    ; STA zp (3 cyc) vs PHA (3 cyc) - same for save
    ; LDA zp (3 cyc) vs PLA (4 cyc) - 1 cycle faster per register!
    irq_save_a        = $B8     ; 1 byte
    irq_save_x        = $B9     ; 1 byte
    irq_save_y        = $BA     ; 1 byte

    ; =========================================================================
    ; NMI-ONLY VARIABLES ($BB-$C2)
    ; =========================================================================
    ; Used by NMI context (song_player.asm, tracker_api.asm).
    ; IRQ must NEVER write to these! (IRQ can't interrupt NMI anyway)
    
    trk_overflow      = $BB     ; 1 byte  - Pitch overflow flag
    trk_ptr           = $BC     ; 2 bytes - NMI-ONLY temp pointer *** CRITICAL ***
    seq_ptr           = $BC     ; ALIAS   - Same location, used by seq parsing
    
    ; Volume Control (when VOLUME_CONTROL=1)
    trk0_vol_shift    = $BE     ; 1 byte  - Channel 0 volume (<<4)
    trk1_vol_shift    = $BF     ; 1 byte  - Channel 1 volume (<<4)
    
    ; NMI Register Saves - zero-page saves 3 cycles total vs stack!
    ; Entry: STA+STX+STY (9 cyc) vs PHA+TXA+PHA+TYA+PHA (13 cyc) = 4 faster
    ; Exit:  LDA+LDX+LDY (9 cyc) vs PLA+TAY+PLA+TAX+PLA (16 cyc) = 7 faster
    ; Total: 11 cycles saved per NMI! Safe because NMI cannot nest.
    nmi_save_a        = $C0     ; 1 byte
    nmi_save_x        = $C1     ; 1 byte
    nmi_save_y        = $C2     ; 1 byte

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
