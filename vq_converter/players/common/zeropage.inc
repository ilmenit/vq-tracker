; ==========================================================================
; ZERO PAGE DEFINITIONS
; ==========================================================================
; Memory layout for VQ sample playback and tracker sequencer.
;
; =========================================================================
; ZERO PAGE MEMORY MAP (Atari 8-bit)
; =========================================================================
; $00-$0F: OS critical (do not touch)
; $10-$1F: OS/DOS vectors (avoid)
; $20-$2F: ZIOCB - safe if not using CIO during playback
; $30-$3F: SIO variables - safe if not using SIO during playback
; $40-$7F: OS/DOS work area (avoid)
; $80-$D3: APPLICATION RESERVED - free to use!
; $D4-$FF: FP area - safe if not using floating point
;
; Our player uses: $20-$3F (during playback only) + $80-$FF
; =========================================================================
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
; TRACKER mode uses $20-$3F + $80-$FF for 3-channel polyphonic playback.
; Non-TRACKER mode uses simpler layout for single-channel players.
; =========================================================================

.ifdef TRACKER

; ==========================================================================
; TRACKER MODE - 3-Channel Polyphonic Player
; ==========================================================================

    ; =========================================================================
    ; ZIOCB/SIO AREA ($20-$3F) - Safe during playback (no CIO/SIO calls)
    ; =========================================================================
    ; These 32 bytes are free because we don't do file I/O during playback.
    ; WARNING: Contents will be lost if CIO/SIO is called!
    
    ; --- Volume Staging (when VOLUME_CONTROL=1) ---
    prep0_vol         = $20     ; 1 byte  - Channel 0 volume staging
    prep1_vol         = $21     ; 1 byte  - Channel 1 volume staging
    prep2_vol         = $22     ; 1 byte  - Channel 2 volume staging
    
    ; --- Channel 2 Staging (overflow from $FF) ---
    prep2_end_lo      = $23     ; 1 byte  - Channel 2 end pointer low
    prep2_end_hi      = $24     ; 1 byte  - Channel 2 end pointer high
    prep2_vq_lo       = $25     ; 1 byte  - Channel 2 VQ cache low
    prep2_vq_hi       = $26     ; 1 byte  - Channel 2 VQ cache high
    
    ; --- Reserved for future use ($27-$3F) ---
    ; 25 bytes available for expansion
    
    ; =========================================================================
    ; APPLICATION AREA ($80-$FF) - Always safe
    ; =========================================================================

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

    ; =========================================================================
    ; SONG PLAYER VARIABLES ($C3-$FF) - Moved from regular memory for speed
    ; =========================================================================
    ; These are initialized by seq_init, not with .byte directives.
    ; Zero-page access saves 1 cycle per LDA/STA (3 vs 4 cycles).
    
    ; --- Hot Path Variables (checked every row) ---
    seq_evt_row       = $C3     ; 3 bytes - Next event row per channel
    seq_local_row_zp  = $C6     ; 3 bytes - Local row counter per channel
    evt_trigger       = $C9     ; 3 bytes - Trigger flags per channel
    
    ; --- Main Loop Variables (checked every frame) ---
    vcount_phase      = $CC     ; 1 byte  - VCOUNT phase for frame detection
    last_playing      = $CD     ; 1 byte  - Previous playing state
    
    ; --- Event Data (when events fire) ---
    evt_note          = $CE     ; 3 bytes - Note per channel
    evt_inst          = $D1     ; 3 bytes - Instrument per channel
    evt_vol           = $D4     ; 3 bytes - Volume per channel
    
    ; --- Event Parsing ---
    seq_evt_ptr_lo    = $D7     ; 3 bytes - Event pointer low byte
    seq_evt_ptr_hi    = $DA     ; 3 bytes - Event pointer high byte
    seq_last_inst     = $DD     ; 3 bytes - Last instrument per channel
    seq_last_vol      = $E0     ; 3 bytes - Last volume per channel
    
    ; --- Pattern Wrap ---
    seq_ptn_len       = $E3     ; 3 bytes - Pattern length per channel
    seq_ptn_start_lo  = $E6     ; 3 bytes - Pattern start low byte
    seq_ptn_start_hi  = $E9     ; 3 bytes - Pattern start high byte
    
    ; --- Staging Area (COMMIT phase is inside SEI - speed critical!) ---
    ; Channel 0 staging
    prep0_pitch_lo    = $EC     ; 1 byte
    prep0_pitch_hi    = $ED     ; 1 byte
    prep0_stream_lo   = $EE     ; 1 byte
    prep0_stream_hi   = $EF     ; 1 byte
    prep0_end_lo      = $F0     ; 1 byte
    prep0_end_hi      = $F1     ; 1 byte
    prep0_vq_lo       = $F2     ; 1 byte
    prep0_vq_hi       = $F3     ; 1 byte
    ; Channel 1 staging
    prep1_pitch_lo    = $F4     ; 1 byte
    prep1_pitch_hi    = $F5     ; 1 byte
    prep1_stream_lo   = $F6     ; 1 byte
    prep1_stream_hi   = $F7     ; 1 byte
    prep1_end_lo      = $F8     ; 1 byte
    prep1_end_hi      = $F9     ; 1 byte
    prep1_vq_lo       = $FA     ; 1 byte
    prep1_vq_hi       = $FB     ; 1 byte
    ; Channel 2 staging (complete - using $20-$26 for overflow)
    prep2_pitch_lo    = $FC     ; 1 byte
    prep2_pitch_hi    = $FD     ; 1 byte
    prep2_stream_lo   = $FE     ; 1 byte
    prep2_stream_hi   = $FF     ; 1 byte
    ; NOTE: prep2_end_*, prep2_vq_*, prep*_vol are at $20-$26 (ZIOCB area)

; NOTE: trk2_vol_shift is in regular memory (song_player.asm) because
; we ran out of contiguous zero-page space for 3 volume variables.

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
