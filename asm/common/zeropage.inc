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
; Our player uses: $27-$33 (during playback only) + $80-$FF
; =========================================================================
;
; =========================================================================
; CRITICAL: IRQ/NMI RACE CONDITION PREVENTION
; =========================================================================
; IRQ and NMI MUST use COMPLETELY SEPARATE temp variables.
;
;   IRQ-ONLY ($B2-$B4):
;     irq_ptr     - Temp pointer for VQ vector loading in IRQ handler
;     irq_busy    - Flag: $FF while IRQ is running
;
;   NMI-ONLY ($BC-$BD):
;     trk_ptr     - Temp pointer for tracker_api.asm
;
; TRACKER mode uses $27-$33 + $80-$FF for 4-channel polyphonic playback.
; Non-TRACKER mode uses simpler layout for single-channel players.
; =========================================================================

.ifdef TRACKER

; ==========================================================================
; TRACKER MODE - 4-Channel Polyphonic Player
; ==========================================================================

    ; =========================================================================
    ; ZIOCB AREA - Channel 3 State ($27-$33)
    ; =========================================================================
    ; 4th channel placed in ZIOCB area because $80-$FF is full with 3 channels.
    ; Still zero-page = same 3-cycle access speed as other channels.
    ; Safe because we don't do CIO/SIO during playback.

    trk3_stream_ptr   = $27     ; 2 bytes - Position in VQ index stream
    trk3_stream_end   = $29     ; 2 bytes - End of sample data
    trk3_sample_ptr   = $2B     ; 2 bytes - Current VQ vector address
    trk3_vector_offset= $2D     ; 1 byte  - Position within vector (0-15)
    trk3_pitch_frac   = $2E     ; 1 byte  - Pitch accumulator fraction
    trk3_pitch_int    = $2F     ; 1 byte  - Pitch accumulator integer
    trk3_pitch_step   = $30     ; 2 bytes - 8.8 fixed-point pitch step
    trk3_active       = $32     ; 1 byte  - $FF=active, $00=inactive
    trk3_note         = $33     ; 1 byte  - Current note (for debug)

    ; =========================================================================
    ; APPLICATION AREA ($80-$FF)
    ; =========================================================================

    ; --- Channel 0 State ($80-$8C) ---
    trk0_stream_ptr   = $80     ; 2 bytes
    trk0_stream_end   = $82     ; 2 bytes
    trk0_sample_ptr   = $84     ; 2 bytes
    trk0_vector_offset= $86     ; 1 byte
    trk0_pitch_frac   = $87     ; 1 byte
    trk0_pitch_int    = $88     ; 1 byte
    trk0_pitch_step   = $89     ; 2 bytes
    trk0_active       = $8B     ; 1 byte
    trk0_note         = $8C     ; 1 byte

    ; --- Sequencer Core State ($8D-$8F) ---
    seq_row           = $8D     ; 1 byte
    seq_tick          = $8E     ; 1 byte
    seq_playing       = $8F     ; 1 byte

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
    seq_songline      = $9D     ; 1 byte
    parse_temp        = $9E     ; 1 byte
    parse_channel     = $9F     ; 1 byte

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
    seq_speed         = $AD     ; 1 byte
    seq_max_len       = $AE     ; 1 byte
    last_key_state    = $AF     ; 1 byte

    ; =========================================================================
    ; IRQ-ONLY VARIABLES ($B0-$BA)
    ; =========================================================================
    chn_idx           = $B0     ; 1 byte
    last_key_code     = $B1     ; 1 byte
    irq_ptr           = $B2     ; 2 bytes - IRQ-ONLY temp pointer
    irq_busy          = $B4     ; 1 byte
    sample_ptr        = $B5     ; 2 bytes
    nibble_state      = $B7     ; 1 byte
    irq_save_a        = $B8     ; 1 byte
    irq_save_x        = $B9     ; 1 byte
    irq_save_y        = $BA     ; 1 byte

    ; =========================================================================
    ; NMI-ONLY VARIABLES ($BB-$C2)
    ; =========================================================================
    trk_overflow      = $BB     ; 1 byte
    trk_ptr           = $BC     ; 2 bytes - NMI-ONLY temp pointer
    seq_ptr           = $BC     ; ALIAS

    ; Volume Control (when VOLUME_CONTROL=1)
    trk0_vol_shift    = $BE     ; 1 byte
    trk1_vol_shift    = $BF     ; 1 byte

    nmi_save_a        = $C0     ; 1 byte
    nmi_save_x        = $C1     ; 1 byte
    nmi_save_y        = $C2     ; 1 byte

    ; =========================================================================
    ; SONG PLAYER VARIABLES ($C3-$F8) - 4-channel indexed arrays
    ; =========================================================================
    ; All arrays are 4 bytes wide (indexed by X=0..3).

    seq_evt_row       = $C3     ; 4 bytes
    seq_local_row_zp  = $C7     ; 4 bytes
    evt_trigger       = $CB     ; 4 bytes

    vcount_phase      = $CF     ; 1 byte
    ; $D0 unused (was last_playing, removed in wait_loop/main_loop split)

    evt_note          = $D1     ; 4 bytes
    evt_inst          = $D5     ; 4 bytes
    evt_vol           = $D9     ; 4 bytes

    seq_evt_ptr_lo    = $DD     ; 4 bytes
    seq_evt_ptr_hi    = $E1     ; 4 bytes
    seq_last_inst     = $E5     ; 4 bytes
    seq_last_vol      = $E9     ; 4 bytes

    seq_ptn_len       = $ED     ; 4 bytes
    seq_ptn_start_lo  = $F1     ; 4 bytes
    seq_ptn_start_hi  = $F5     ; 4 bytes
    ; End: $F8

; NOTE: All prep*_* staging and trk2/3_vol_shift are in regular memory
; (song_player.asm) because they are only used at row rate (~8Hz).

seq_local_row = seq_local_row_zp

.else

; ==========================================================================
; NON-TRACKER MODE - Simple Single-Channel Players
; ==========================================================================

    stream_ptr      = $80       ; 2 bytes
    stream_end      = $82       ; 2 bytes
    sample_ptr      = $8A       ; 2 bytes
    sample_len      = $8C       ; 1 byte

    .ifndef USE_STACK_IRQ
    irq_save_a      = $8D       ; 1 byte
    irq_save_x      = $8E       ; 1 byte
    irq_save_y      = $8F       ; 1 byte
    .endif

    ptr_lens        = $84       ; 2 bytes
    ptr_lo          = $86       ; 2 bytes
    ptr_hi          = $88       ; 2 bytes
    slide_counter_lo = $90      ; 1 byte
    slide_counter_hi = $91      ; 1 byte
    nibble_state    = $92       ; 1 byte
    sample_finished = $93       ; 1 byte
    current_sample  = $94       ; 1 byte
    pitch_step      = $95       ; 2 bytes
    pitch_frac      = $97       ; 1 byte
    pitch_int       = $98       ; 1 byte
    pitch_save_x    = $99       ; 1 byte

.endif

; ==========================================================================
; END OF ZERO PAGE DEFINITIONS
; ==========================================================================
