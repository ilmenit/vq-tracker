; ==========================================================================
; SONG PLAYER - POKEY VQ Tracker (Main Module)
; ==========================================================================
; Version: 4.0 - 4-Channel Polyphonic
;
; Features:
;   - 4-channel polyphonic playback via VQ-compressed samples (AUDC1-AUDC4)
;   - Per-songline speed control (1-255 ticks per row)
;   - Variable-length event encoding for compact pattern storage
;   - Two-phase note triggering (minimal IRQ disable time)
;   - Keyboard control: SPACE=play/stop, R=restart
;   - Optional volume control per note (VOLUME_CONTROL=1)
;   - Optional blank screen mode for max CPU (BLANK_SCREEN=1)
;
; ==========================================================================

; ==========================================================================
; INCLUDES - Configuration and Common Definitions
; ==========================================================================
    icl "common/atari.inc"      ; Hardware register definitions
    
    TRACKER = 1                 ; Enable tracker mode in zeropage.inc
    icl "common/zeropage.inc"   ; Zero-page variable definitions
    icl "common/macros.inc"     ; Utility macros
    icl "common/copy_os_ram.asm"; ROM-under-RAM setup
    icl "VQ_CFG.asm"            ; VQ converter configuration
    icl "SONG_CFG.asm"          ; Song-specific settings (VOLUME_CONTROL, etc.)
    
; ==========================================================================
; DEFAULT CONFIGURATION
; ==========================================================================
    .ifndef BLANK_SCREEN
        BLANK_SCREEN = 0        ; Default: display enabled
    .endif
    .ifndef KEY_CONTROL
        KEY_CONTROL = 0         ; Default: minimal keyboard (play-once mode)
    .endif
    .ifndef VOLUME_CONTROL
        VOLUME_CONTROL = 0      ; Default: no volume control
    .endif
    ; Tracker mode requires these — default if converter omitted them
    ; (happens when converter runs in algo=raw mode)
    .ifndef ALGO_FIXED
        ALGO_FIXED = 1
    .endif
    .ifndef MULTI_SAMPLE
        MULTI_SAMPLE = 1
    .endif
    .ifndef PITCH_CONTROL
        PITCH_CONTROL = 1
    .endif
    .ifndef MIN_VECTOR
        MIN_VECTOR = 8          ; Default vector size for VQ code paths
    .endif
    
; ==========================================================================
; CONFIGURATION VALIDATION
; ==========================================================================
    .ifndef MULTI_SAMPLE
        .error "song_player.asm requires MULTI_SAMPLE=1"
    .endif
    .ifndef PITCH_CONTROL
        .error "song_player.asm requires PITCH_CONTROL=1"
    .endif
    .ifndef ALGO_FIXED
        .error "song_player.asm requires ALGO_FIXED=1"
    .endif

; ==========================================================================
; SMC OPCODE CONSTANTS
; ==========================================================================
; Self-modifying code opcodes for the IRQ handler dispatch mechanism.
; Defined here so they are available before the include of process_row.
    OPCODE_BMI = $30            ; BMI: dispatch = no-pitch
    OPCODE_BPL = $10            ; BPL: dispatch = has-pitch
    OPCODE_BCS = $B0            ; BCS: VQ boundary hit (A >= MIN_VECTOR)
    OPCODE_BEQ = $F0            ; BEQ: RAW boundary hit (A == 0, page wrap)

; ==========================================================================
; CODE START
; ==========================================================================
    .ifndef START_ADDRESS
        START_ADDRESS = $2000   ; Default if not set by SONG_CFG
    .endif
    ORG START_ADDRESS

; ==========================================================================
; CONSTANTS
; ==========================================================================
SILENCE     = $10               ; AUDC value for silence (volume-only, vol=0)
COL_STOPPED = $00               ; Background color when stopped (black)
COL_PLAYING = $74               ; Background color when playing (blue)

.ifdef USE_BANKING
PORTB_MAIN  = $FE               ; PORTB: main RAM visible, OS ROM disabled
.endif

; ==========================================================================
; DISPLAY LIST AND TEXT
; ==========================================================================
.if BLANK_SCREEN = 0
; --- Normal display: 4 text lines (always visible) ---
; Line 1: Song name (centered, from SONG_INFO.asm)
; Line 2: Author name (centered, from SONG_INFO.asm)
; Line 3: VQ TRACKER banner
; Line 4: SONG/ROW/SPD status
text_line1:
    icl "SONG_INFO.asm"             ; lines 1+2: name (40) + author (40)
.if KEY_CONTROL = 1
    dta d"VQ TRACKER - [SPACE] play/stop [R] reset"  ; line 3 (40 chars)
.else
    dta d"               VQ TRACKER               "  ; line 3 (40 chars)
.endif
    dta d"       SONG:"
song_pos_display:
    dta d"00"
    dta d"   ROW:"
row_display:
    dta d"00"
    dta d"   SPD:"
speed_display:
    dta d"06"
    dta d"        "
dlist:
    .byte $70,$70,$70           ; 24 blank lines
    .byte $42,<text_line1,>text_line1  ; Mode 2 text line 1
    .byte $02,$02,$02           ; Mode 2 text lines 2, 3, 4
    .byte $41,<dlist,>dlist     ; Jump and wait for VBL
.else
; --- Blank screen mode: display visible when stopped, blank when playing ---
text_line1:
    icl "SONG_INFO.asm"             ; lines 1+2: name (40) + author (40)
.if KEY_CONTROL = 1
    dta d"VQ TRACKER - [SPACE] play/stop [R] reset"  ; line 3 (40 chars)
.else
    dta d"               VQ TRACKER               "  ; line 3 (40 chars)
.endif
    dta d"       SONG:"
song_pos_display:
    dta d"00"
    dta d"   ROW:"
row_display:
    dta d"00"
    dta d"   SPD:"
speed_display:
    dta d"06"
    dta d"        "
dlist:
    .byte $70,$70,$70           ; 24 blank lines
    .byte $42,<text_line1,>text_line1  ; Mode 2 text line 1
    .byte $02,$02,$02           ; Mode 2 text lines 2, 3, 4
    .byte $41,<dlist,>dlist     ; Jump and wait for VBL
.endif

; ==========================================================================
; MAIN ENTRY POINT
; ==========================================================================
start:
    sei                         ; Disable interrupts during setup
    ldx #$FF
    txs                         ; Initialize stack pointer
    
    ; --- Disable OS ---
    lda #0
    sta NMIEN                   ; Disable NMI
    sta IRQEN                   ; Disable IRQ
    sta DMACTL                  ; Disable display DMA
    lda #$FE
    sta PORTB                   ; Enable RAM under ROM
    
    ; --- Setup interrupt vectors ---
    lda #<nmi_stub
    sta $FFFA
    lda #>nmi_stub
    sta $FFFA+1
    
    lda #<Tracker_IRQ
    sta $FFFE
    lda #>Tracker_IRQ
    sta $FFFE+1

    ; --- Setup display ---
    lda #<dlist
    sta DLISTL
    lda #>dlist
    sta DLISTH
    lda #$FC
    sta $D409                   ; CHBASE=$FC → charset at $FC00 (relocated)
    lda #$22                    ; Enable DL DMA ($20) + normal playfield ($02)
    sta DMACTL                  ; User sees "press SPACE to play"
    lda #$C0                    ; Enable VBI + DLI
    sta NMIEN
    
    ; --- Initialize keyboard ---
    lda #0
    sta SKCTL
    lda #3
    sta SKCTL                   ; Enable keyboard scan
    
    ; --- Initialize VCOUNT tracking ---
    lda VCOUNT
    and #$80
    sta vcount_phase
    
    ; --- Initialize sequencer ---
    jsr seq_init
    
    ; --- Setup POKEY for audio ---
    jsr Pokey_Setup
    
    ; --- Initialize display colors ---
    lda #$0E                    ; White/bright luminance
    sta COLPF1
    lda #$94                    ; Blue hue
    sta COLPF2
    lda #COL_STOPPED            ; Black background when stopped
    sta COLBK
    
    ; --- Enable timer IRQ ---
    lda #IRQ_MASK
    sta IRQEN
    lda #$00
    sta STIMER                  ; Start timers
    
    cli                         ; Enable interrupts
    jmp wait_loop               ; Enter idle state (wait for SPACE to play)

; ==========================================================================
; IRQ HANDLER — placed before process_row.asm so CHANNEL_IRQ macro labels
; (chN_vq_no_pitch, chN_raw_pitch, etc.) are defined before process_row
; references them.  The IRQ handler is entered via the interrupt vector
; ($FFFE), not sequential code flow, so its source position is irrelevant.
; ==========================================================================
.ifdef USE_BANKING
    icl "tracker/tracker_irq_banked.asm"
.else
    icl "tracker/tracker_irq_speed.asm"
.endif

; ==========================================================================
; PROCESS ROW - Called from main_loop when a new row is due
; ==========================================================================
do_process_row:
    icl "tracker/process_row.asm"
    jmp ml_after_row            ; Return to main loop after processing

; ==========================================================================
; WAIT LOOP - Idle state (screen ON, waiting for SPACE)
; ==========================================================================
; State 1: Pre-play and post-play. Screen is always enabled.
; Displays text and current position. Waits for SPACE to start playback.
; In KEY_CONTROL=1 mode, R resets position to the beginning.
; ==========================================================================
wait_loop:
    ; --- Frame detection via VCOUNT ---
    lda VCOUNT
    and #$80
    tax
    cmp vcount_phase
    beq wl_check_keys
    
    stx vcount_phase
    txa
    bne wl_check_keys           ; Only act on 1->0 transition
    
    ; --- New frame: update display ---
    jsr update_display
    
wl_check_keys:
    ; --- Check for keypress ---
    lda SKSTAT
    and #$04
    bne wait_loop               ; No key pressed, keep waiting
    lda SKSTAT                  ; Double-read for debounce
    and #$04
    bne wait_loop
    
    lda KBCODE
    and #$3F
    
    ; --- SPACE ($21) = start playback ---
    cmp #$21
    beq wl_start_play
    
.if KEY_CONTROL = 1
    ; --- R ($28) = reset to beginning ---
    cmp #$28
    beq wl_do_reset
.endif
    
    ; --- Unknown key: wait for release, continue ---
wl_key_release:
    lda SKSTAT
    and #$04
    beq wl_key_release
    jmp wait_loop

.if KEY_CONTROL = 1
wl_do_reset:
    ; Reset sequencer to beginning (stays in idle state)
    jsr seq_init
    ; Wait for R key release
wl_reset_release:
    lda SKSTAT
    and #$04
    beq wl_reset_release
    lda SKSTAT
    and #$04
    beq wl_reset_release
    jmp wait_loop
.endif

wl_start_play:
    ; Wait for SPACE release before starting (prevents immediate stop)
wl_space_release:
    lda SKSTAT
    and #$04
    beq wl_space_release
    lda SKSTAT
    and #$04
    beq wl_space_release
    
    ; --- Transition to playback ---
.if BLANK_SCREEN = 1
    lda #0
    sta DMACTL                  ; Screen OFF for max CPU
.endif
    lda #COL_PLAYING
    sta COLBK
    lda #$FF
    sta seq_playing
.if KEY_CONTROL = 1
    lda #$FF
    sta last_key_code           ; Reset key debounce state
.endif
    jmp main_loop

; ==========================================================================
; MAIN LOOP - Playback state (screen off if BLANK_SCREEN=1)
; ==========================================================================
; State 2: Active playback. Processes ticks and rows.
; In KEY_CONTROL=1 mode: SPACE=stop, R=restart (return to wait_loop).
; In KEY_CONTROL=0 mode: no keyboard, plays once then returns to wait_loop.
; ==========================================================================
main_loop:
    ; --- Frame detection via VCOUNT ---
    lda VCOUNT
    and #$80
    tax
    cmp vcount_phase
    beq ml_no_vblank            ; No phase change
    
    stx vcount_phase            ; Update phase
    txa
    bne ml_no_vblank            ; Only act on 1->0 transition
    
    ; =====================================================================
    ; NEW FRAME - Process tick
    ; =====================================================================
    inc seq_tick
    lda seq_tick
    cmp seq_speed
    bcc ml_after_row            ; Not time for new row
    
    ; --- New row ---
    lda #0
    sta seq_tick
    jmp do_process_row
    
ml_after_row:
    ; --- Check if song has ended (process_row sets seq_playing=0) ---
    lda seq_playing
    beq ml_song_ended

    ; --- Update display (only when screen is visible) ---
.if BLANK_SCREEN = 0
    jsr update_display
.endif

ml_no_vblank:
    ; =====================================================================
    ; KEYBOARD HANDLING (playback state)
    ; =====================================================================

.if KEY_CONTROL = 1
    ; --- Full keyboard control mode ---
    lda last_key_code
    cmp #$FF
    beq ml_no_key_held          ; No key held, check for new press
    jmp ml_check_release        ; Key held, check for release (far branch)
    
ml_no_key_held:
    ; --- Check for new keypress ---
    lda SKSTAT
    and #$04
    bne ml_continue
    lda SKSTAT                  ; Double-read for debounce
    and #$04
    bne ml_continue
    
    ; --- Process keypress ---
    lda KBCODE
    and #$3F
    sta last_key_code
    
    ; --- SPACE key ($21) = stop ---
    cmp #$21
    beq ml_do_stop
    
    ; --- R key ($28) = restart ---
    cmp #$28
    beq ml_do_restart
    jmp ml_continue

ml_do_stop:
    ; Stop playing, silence channels, return to idle
    jsr silence_channels
    jmp return_to_idle
    
ml_do_restart:
    ; Silence channels, reset sequencer, return to idle
    jsr silence_channels
    jsr seq_init
    jmp return_to_idle

ml_check_release:
    lda SKSTAT
    and #$04
    beq ml_continue
    lda SKSTAT                  ; Double-read for debounce
    and #$04  
    beq ml_continue
    
    ; Key released
    lda #$FF
    sta last_key_code

.else
    ; --- Minimal keyboard mode (KEY_CONTROL=0) ---
    ; No keyboard during playback. Song stops by itself.
.endif

ml_continue:
    jmp main_loop

; --- Song ended (process_row set seq_playing=0) ---
ml_song_ended:
    jsr silence_channels
    jmp return_to_idle

; ==========================================================================
; SHARED SUBROUTINES for state transitions
; ==========================================================================

silence_channels:
    ; Silence all 4 channels
    lda #0
    sta seq_playing
    sta trk0_active
    sta trk1_active
    sta trk2_active
    sta trk3_active
    lda #SILENCE
    sta AUDC1
    sta AUDC2
    sta AUDC3
    sta AUDC4
    rts

return_to_idle:
    ; Restore screen and return to wait_loop
.if BLANK_SCREEN = 1
    lda #$22
    sta DMACTL                  ; Screen back ON
.endif
    lda #COL_STOPPED
    sta COLBK
.if KEY_CONTROL = 1
    ; Wait for key release before returning (prevents ghost keypress in wait_loop)
@rti_release:
    lda SKSTAT
    and #$04
    beq @rti_release
    lda SKSTAT
    and #$04
    beq @rti_release
.endif
    jmp wait_loop

; ==========================================================================
; NMI STUB
; ==========================================================================
nmi_stub:
    rti

; ==========================================================================
; INCLUDE SUBROUTINES
; ==========================================================================
    icl "tracker/parse_event.asm"       ; Event parsing (called 4x per row)
    icl "tracker/seq_init.asm"          ; Initialization
    icl "tracker/seq_load_songline.asm" ; Songline loading
    icl "tracker/update_display.asm"    ; Display update
    icl "common/pokey_setup.asm"        ; POKEY initialization

; ==========================================================================
; INCLUDE DATA TABLES
; ==========================================================================

.ifdef USE_BANKING
; --- Banking Mode Memory Layout ---
; $2000-$3BFF: code + read-only tables + staging (main RAM, always visible)
; $3C00-$3FFF: free (charset relocated to $FC00)
; $4000-$7FFF: bank window (sample audio data, swapped per bank)
; $8000-$CFFF: song data region A (patterns + songlines, 20KB)
; $D000-$D7FF: hardware I/O (untouchable)
; $D800-$FBFF: song data region B (overflow patterns, 9KB)
; $FC00-$FFFF: relocated charset (CHBASE=$FC)
;
; Total song data capacity: 29,696 bytes (~29KB)
; Read-only tables go BEFORE $4000 to leave maximum space for song data.
; These are accessed via absolute addressing so their address doesn't matter.

_CODE_END_ = *
; --- Read-only lookup tables (placed after code, before bank window) ---
    icl "pitch/pitch_tables.asm"
_AFTER_PITCH_ = *
    icl "pitch/VOLUME_SCALE.asm"
_AFTER_VOLSCALE_ = *
    icl "SAMPLE_DIR.asm"            ; SAMPLE_START/END + SAMPLE_MODE tables
_AFTER_SAMPLEDIR_ = *
    icl "VQ_LO.asm"
    icl "VQ_HI.asm"
_AFTER_VQ_ = *
    icl "BANK_CFG.asm"              ; SAMPLE_PORTB, SAMPLE_BANK_SEQ, etc.
_AFTER_BANKCFG_ = *

; --- Staging and channel variables (read/write, row-rate access) ---

; Staging area (used by process_row at row rate, not IRQ rate)
; Channel 0 staging
prep0_pitch_lo:   .byte 0
prep0_pitch_hi:   .byte 0
prep0_stream_lo:  .byte 0
prep0_stream_hi:  .byte 0
prep0_end_lo:     .byte 0
prep0_end_hi:     .byte 0
prep0_vq_lo:      .byte 0
prep0_vq_hi:      .byte 0
prep0_mode:       .byte 0     ; 0=VQ, non-zero=RAW
prep0_has_pitch:  .byte 0     ; 0=no pitch, $FF=has pitch
; Channel 1 staging
prep1_pitch_lo:   .byte 0
prep1_pitch_hi:   .byte 0
prep1_stream_lo:  .byte 0
prep1_stream_hi:  .byte 0
prep1_end_lo:     .byte 0
prep1_end_hi:     .byte 0
prep1_vq_lo:      .byte 0
prep1_vq_hi:      .byte 0
prep1_mode:       .byte 0
prep1_has_pitch:  .byte 0
; Channel 2 staging
prep2_pitch_lo:   .byte 0
prep2_pitch_hi:   .byte 0
prep2_stream_lo:  .byte 0
prep2_stream_hi:  .byte 0
prep2_end_lo:     .byte 0
prep2_end_hi:     .byte 0
prep2_vq_lo:      .byte 0
prep2_vq_hi:      .byte 0
prep2_mode:       .byte 0
prep2_has_pitch:  .byte 0
; Channel 3 staging
prep3_pitch_lo:   .byte 0
prep3_pitch_hi:   .byte 0
prep3_stream_lo:  .byte 0
prep3_stream_hi:  .byte 0
prep3_end_lo:     .byte 0
prep3_end_hi:     .byte 0
prep3_vq_lo:      .byte 0
prep3_vq_hi:      .byte 0
prep3_mode:       .byte 0
prep3_has_pitch:  .byte 0

; Volume control variables
.if VOLUME_CONTROL = 1
prep0_vol:        .byte $F0
prep1_vol:        .byte $F0
prep2_vol:        .byte $F0
prep3_vol:        .byte $F0
trk2_vol_shift:   .byte $F0    ; Channel 2 volume (pre-shifted)
trk3_vol_shift:   .byte $F0    ; Channel 3 volume (pre-shifted)
.endif

; Per-channel bank tracking (cold path — accessed at boundary rate ~17ms)
ch0_bank_seq_idx: .byte 0     ; Index into SAMPLE_BANK_SEQ for current bank
ch0_banks_left:   .byte 0     ; Remaining bank crossings (0 = in last bank)
ch0_data_hi:      .byte $40   ; Hi byte of data start (VQ=$48, RAW=$40)
ch1_bank_seq_idx: .byte 0
ch1_banks_left:   .byte 0
ch1_data_hi:      .byte $40
ch2_bank_seq_idx: .byte 0
ch2_banks_left:   .byte 0
ch2_data_hi:      .byte $40
ch3_bank_seq_idx: .byte 0
ch3_banks_left:   .byte 0
ch3_data_hi:      .byte $40

; Staging for bank setup during note trigger (process_row)
prep0_portb:      .byte PORTB_MAIN
prep1_portb:      .byte PORTB_MAIN
prep2_portb:      .byte PORTB_MAIN
prep3_portb:      .byte PORTB_MAIN
prep0_seq_off:    .byte 0     ; Offset into SAMPLE_BANK_SEQ
prep1_seq_off:    .byte 0
prep2_seq_off:    .byte 0
prep3_seq_off:    .byte 0
prep0_n_banks:    .byte 1     ; Number of banks (for banks_left = n-1)
prep1_n_banks:    .byte 1
prep2_n_banks:    .byte 1
prep3_n_banks:    .byte 1
prep0_data_hi:    .byte $40   ; Hi byte of data start in bank (VQ=$48, RAW=$40)
prep1_data_hi:    .byte $40
prep2_data_hi:    .byte $40
prep3_data_hi:    .byte $40

; Code + tables + staging must not reach bank window ($4000)
    .if * > $4000
        .error "Code+tables exceed $4000 bank window! Lower start address or reduce tables."
    .endif

; =========================================================================
; SONG DATA — Split across two regions (I/O gap at $D000-$D7FF)
; =========================================================================
; Region A: $8000-$CFFF  (20,480 bytes) — metadata + patterns
; Region B: $D800-$FBFF  ( 9,216 bytes) — overflow patterns (if any)
; Gap:      $D000-$D7FF  (hardware I/O, untouchable)
; Charset:  $FC00-$FFFF  (relocated from $E000 by copy_os_ram.asm)
; Total:    29,696 bytes — nearly double the old 16KB limit
; =========================================================================

; --- Region A: $8000-$CFFF ---
    ORG $8000
    icl "SONG_DATA.asm"
_AFTER_SONG_A_ = *

    .if _AFTER_SONG_A_ > $D000
        .error "SONG_DATA.asm overflows region A ($8000-$CFFF)! Split required."
    .endif

; --- Region B: $D800-$FBFF (overflow patterns, may be empty) ---
    ORG $D800
    icl "SONG_DATA_2.asm"
_AFTER_SONG_B_ = *

    .if _AFTER_SONG_B_ > $FC00
        .error "Song data exceeds 29KB! Region B ($D800-$FBFF) overflowed into charset."
    .endif

.else
; --- 64KB Mode: everything contiguous ---

_DATA_START_ = *
    icl "pitch/pitch_tables.asm"
_AFTER_PITCH_ = *

    icl "pitch/VOLUME_SCALE.asm"
_AFTER_VOLSCALE_ = *

; ==========================================================================
; INCLUDE SONG AND SAMPLE DATA
; ==========================================================================
    icl "SONG_DATA.asm"
_AFTER_SONG_ = *
    icl "SAMPLE_DIR.asm"        ; SAMPLE_START/END + SAMPLE_MODE tables
_AFTER_SAMPLEDIR_ = *

    ; 64KB mode: global codebook in main RAM
    icl "VQ_LO.asm"
    icl "VQ_HI.asm"
    icl "VQ_BLOB.asm"           ; Codebook data (always in main RAM)
_AFTER_VQ_ = *
    ; 64KB mode: all sample data inline in main memory.
    icl "VQ_INDICES.asm"
    icl "RAW_SAMPLES.asm"       ; Page-aligned RAW AUDC data (may be empty)
.endif

; ==========================================================================
; STAGING AREA - 64KB mode only (banking mode places these before $4000)
; ==========================================================================
.ifndef USE_BANKING
; Channel 0 staging
prep0_pitch_lo:   .byte 0
prep0_pitch_hi:   .byte 0
prep0_stream_lo:  .byte 0
prep0_stream_hi:  .byte 0
prep0_end_lo:     .byte 0
prep0_end_hi:     .byte 0
prep0_vq_lo:      .byte 0
prep0_vq_hi:      .byte 0
prep0_mode:       .byte 0     ; 0=VQ, non-zero=RAW
prep0_has_pitch:  .byte 0     ; 0=no pitch, $FF=has pitch
; Channel 1 staging
prep1_pitch_lo:   .byte 0
prep1_pitch_hi:   .byte 0
prep1_stream_lo:  .byte 0
prep1_stream_hi:  .byte 0
prep1_end_lo:     .byte 0
prep1_end_hi:     .byte 0
prep1_vq_lo:      .byte 0
prep1_vq_hi:      .byte 0
prep1_mode:       .byte 0
prep1_has_pitch:  .byte 0
; Channel 2 staging
prep2_pitch_lo:   .byte 0
prep2_pitch_hi:   .byte 0
prep2_stream_lo:  .byte 0
prep2_stream_hi:  .byte 0
prep2_end_lo:     .byte 0
prep2_end_hi:     .byte 0
prep2_vq_lo:      .byte 0
prep2_vq_hi:      .byte 0
prep2_mode:       .byte 0
prep2_has_pitch:  .byte 0
; Channel 3 staging
prep3_pitch_lo:   .byte 0
prep3_pitch_hi:   .byte 0
prep3_stream_lo:  .byte 0
prep3_stream_hi:  .byte 0
prep3_end_lo:     .byte 0
prep3_end_hi:     .byte 0
prep3_vq_lo:      .byte 0
prep3_vq_hi:      .byte 0
prep3_mode:       .byte 0
prep3_has_pitch:  .byte 0

; Volume control variables
.if VOLUME_CONTROL = 1
prep0_vol:        .byte $F0
prep1_vol:        .byte $F0
prep2_vol:        .byte $F0
prep3_vol:        .byte $F0
trk2_vol_shift:   .byte $F0    ; Channel 2 volume (pre-shifted)
trk3_vol_shift:   .byte $F0    ; Channel 3 volume (pre-shifted)
.endif
.endif ; .ifndef USE_BANKING

; ==========================================================================
; ASSEMBLY VALIDATION
; ==========================================================================

.ifdef USE_BANKING
    ; --- Banking mode validation ---
    
    ; Per-bank codebooks: VQ_BLOB not in main RAM (codebook lives in each bank).
    .ifndef CODEBOOK_SIZE
        .error "CODEBOOK_SIZE not defined. tracker_irq_banked.asm must define it."
    .endif
    
    ; Song data overflow checks are inline after SONG_DATA.asm and SONG_DATA_2.asm.
    ; Region A: $8000-$CFFF (20,480 bytes)
    ; Region B: $D800-$FBFF (9,216 bytes, charset at $FC00)
    ; Tables, staging, and BANK_CFG are below $4000 (checked there too).
    
    ; Verify REQUIRED_BANKS is defined (comes from BANK_CFG.asm)
    .ifndef REQUIRED_BANKS
        .error "REQUIRED_BANKS not defined. BANK_CFG.asm missing or empty."
    .endif
    
    ; Verify bank configuration tables exist
    .ifndef SAMPLE_BANK_SEQ
        .error "SAMPLE_BANK_SEQ not defined. BANK_CFG.asm incomplete."
    .endif
    
.else
    ; --- 64KB mode validation ---
    
    .if * > $C000
        .if _AFTER_SONG_ > $C000
            .error "SONG_DATA too large! Song data alone exceeds $C000. Reduce patterns or use extended memory."
        .else
            .error "Memory overflow! All data exceeds $C000. Reduce samples, use VQ, or switch to extended memory."
        .endif
    .endif
    
.endif

; Common: verify SAMPLE_COUNT matches expectations
.ifdef SAMPLE_COUNT
    .if SAMPLE_COUNT > 127
        .error "Too many instruments (max 127)."
    .endif
.endif

; ==========================================================================
; ENTRY POINT
; ==========================================================================
    run start
