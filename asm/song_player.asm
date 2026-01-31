; ==========================================================================
; SONG PLAYER - POKEY VQ Tracker (Main Module)
; ==========================================================================
; Version: 3.8 - Branch-Optimized Layout
;
; This is the main orchestrator that includes all player components.
; Code is split into logical modules in the tracker/ folder for clarity.
;
; Module Organization:
; ====================
;   song_player.asm (this file)
;     ├── Constants, display list, entry point
;     ├── do_process_row (ICL before main_loop for short branches)
;     ├── Main loop with frame timing
;     ├── Keyboard handling
;     └── Includes:
;         ├── tracker/process_row.asm     (included before main_loop)
;         ├── tracker/parse_event.asm     (subroutine - event parsing)
;         ├── tracker/seq_init.asm        (subroutine - initialization)
;         ├── tracker/seq_load_songline.asm (subroutine - songline loading)
;         ├── tracker/update_display.asm  (conditional - display update)
;         └── tracker/tracker_irq_*.asm   (IRQ handler)
;
; Code Layout Rationale:
; ======================
;   process_row.asm (~400 bytes) is placed BEFORE main_loop so that the
;   common-case branches (skipping row processing) stay within 127 bytes.
;   This saves ~3 cycles per frame vs using extended JEQ/JNE instructions.
;
; Features:
; =========
;   - 3-channel polyphonic playback via VQ-compressed samples
;   - Per-songline speed control (1-255 ticks per row)
;   - Variable-length event encoding for compact pattern storage
;   - Two-phase note triggering (minimal IRQ disable time)
;   - Keyboard control: SPACE=play/stop, R=restart
;   - Optional volume control per note (VOLUME_CONTROL=1)
;   - Optional blank screen mode for max CPU (BLANK_SCREEN=1)
;   - Two IRQ modes: speed or size optimized (OPTIMIZE_SPEED)
;
; Memory Layout:
; ==============
;   Zero-page $20-$26: Staging area overflow (ZIOCB area, safe during play)
;   Zero-page $80-$FF: Channel state, sequencer, staging
;   $2000+: Code and data
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
; CODE START
; ==========================================================================
    ORG $2000

; ==========================================================================
; CONSTANTS
; ==========================================================================
SILENCE     = $10               ; AUDC value for silence (volume-only, vol=0)
COL_STOPPED = $00               ; Background color when stopped (black)
COL_PLAYING = $74               ; Background color when playing (blue)

; ==========================================================================
; SEQUENCER STATE - All in zero-page (see zeropage.inc)
; ==========================================================================
; Zero-page allocations:
;   $20-$26: ZIOCB area (prep*_vol, prep2_end_*, prep2_vq_*)
;   $80-$C2: Channel state + sequencer core
;   $C3-$FF: Sequencer arrays + staging
;
; Alias for code compatibility:
seq_local_row = seq_local_row_zp

; ==========================================================================
; DISPLAY LIST
; ==========================================================================
.if BLANK_SCREEN = 0
; --- Normal display: 2 text lines ---
.if KEY_CONTROL = 1
text_line1:
    dta d" VQ TRACKER - [SPACE] play/stop [R] reset"
.else
text_line1:
    dta d"   VQ TRACKER - [SPACE] to play          "
.endif
text_line2:
    dta d"      SONG:"
song_pos_display:
    dta d"00"
    dta d"   ROW:"
row_display:
    dta d"00"
    dta d"   SPD:"
speed_display:
    dta d"06"
    dta d"         "
dlist:
    .byte $70,$70,$70           ; 24 blank lines
    .byte $42,<text_line1,>text_line1  ; Mode 2 text
    .byte $02                   ; Mode 2 text (uses same address calc)
    .byte $41,<dlist,>dlist     ; Jump and wait for VBL
.else
; --- Blank screen: minimal display (shown only when stopped) ---
.if KEY_CONTROL = 1
text_line1:
    dta d" VQ TRACKER - [SPACE] play/stop [R] reset"
.else
text_line1:
    dta d"   VQ TRACKER - [SPACE] to play          "
.endif
dlist:
    .byte $70,$70,$70
    .byte $42,<text_line1,>text_line1
    .byte $41,<dlist,>dlist
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
    lda #$02                    ; Always start with display enabled (normal playfield)
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
    lda #COL_STOPPED
    sta COLBK                   ; Set background color (stopped = black)
    lda #$FF
    sta last_playing            ; Force state change detection on first loop
    
    ; --- Enable timer IRQ ---
    lda #IRQ_MASK
    sta IRQEN
    lda #$00
    sta STIMER                  ; Start timers
    
    cli                         ; Enable interrupts
    jmp main_loop               ; Enter main loop (skip do_process_row!)

; ==========================================================================
; PROCESS ROW - Moved here so main_loop branches stay in range
; ==========================================================================
; Row processing is placed BEFORE main_loop so that the common-case branches
; (skipping row processing) remain short. Only when actually processing a row
; (~1/6 of frames at speed=6) do we pay the JMP overhead.
;
; IMPORTANT: This code block is jumped to from main_loop, NOT fallen into!
; The JMP main_loop above ensures we don't execute this on startup.
;
; Cycle cost comparison:
;   Old (inlined, out-of-range JEQ/JNE): 5 cycles per skip (common case)
;   New (JMP here + JMP back): 6 cycles total, but only when processing
;   Common case (skip): 2-3 cycles (short branch)
; ==========================================================================
do_process_row:
    icl "tracker/process_row.asm"
    jmp ml_check_state_change   ; Return to main loop after processing

; ==========================================================================
; MAIN LOOP
; ==========================================================================
; Frame-driven loop using VCOUNT polling (no NMI needed).
; Processes one row per seq_speed ticks (50 ticks/sec on PAL).
; ==========================================================================
main_loop:
    ; --- Frame detection via VCOUNT ---
    ; VCOUNT bit 7 toggles at mid-screen; we detect 1->0 transition
    lda VCOUNT
    and #$80
    tax
    cmp vcount_phase
    beq ml_no_vblank            ; No phase change (2-3 cycles, in range)
    
    stx vcount_phase            ; Update phase
    txa
    bne ml_no_vblank            ; Only act on 1->0 transition (2-3 cycles)
    
    ; =====================================================================
    ; NEW FRAME - Process tick
    ; =====================================================================
    lda seq_playing
    beq ml_check_state_change   ; Not playing? Skip row processing (2-3 cycles)
    
    ; --- Tick counter ---
    inc seq_tick
    lda seq_tick
    cmp seq_speed
    bcc ml_check_state_change   ; Not time for new row yet (2-3 cycles)
    
    ; --- New row: reset tick and jump to processing ---
    lda #0
    sta seq_tick
    jmp do_process_row          ; Process row (3 cycles, only ~1/6 of frames)
    
ml_check_state_change:
    ; --- Handle play/stop transitions ---
    lda seq_playing
    cmp last_playing
    beq ml_state_done           ; No change
    
    sta last_playing
    beq ml_now_stopped          ; Transition to stopped
    
    ; --- Started playing ---
    lda #COL_PLAYING
.if BLANK_SCREEN = 1
    ldx #0
    stx DMACTL                  ; Disable display for max CPU (0 cycles stolen)
.endif
    bne ml_set_color            ; Always branches
    
ml_now_stopped:
    ; --- Stopped playing ---
    lda #COL_STOPPED
.if BLANK_SCREEN = 1
    ldx #$02                    ; Normal playfield only (no player/missile DMA)
    stx DMACTL                  ; Re-enable minimal display
.endif

ml_set_color:
    sta COLBK

ml_state_done:
    ; --- Update display every frame (if enabled) ---
    ; When BLANK_SCREEN=0, update display regardless of playing state
    ; This shows real-time SONG/ROW/SPD values during playback
.if BLANK_SCREEN = 0
    jsr update_display
.endif

ml_no_vblank:
    ; =====================================================================
    ; KEYBOARD HANDLING
    ; =====================================================================
    ; When KEY_CONTROL=1: Full keyboard control (play/stop/restart)
    ; When KEY_CONTROL=0: Minimal - just SPACE to start, then no checking
    ;                     Saves ~30-50 cycles per main loop iteration
    ; =====================================================================

.if KEY_CONTROL = 1
    ; --- Full keyboard control mode ---
    lda last_key_code
    cmp #$FF
    bne ml_check_release        ; Key still held? Check for release
    
    ; --- Check for new keypress ---
    lda SKSTAT
    and #$04                    ; Bit 2 = key pressed
    bne ml_continue             ; No key? Continue loop
    lda SKSTAT                  ; Double-read for debounce
    and #$04
    bne ml_continue
    
    ; --- Process keypress ---
    lda KBCODE
    and #$3F                    ; Mask to key code
    sta last_key_code
    
    ; --- SPACE key ($21) = play/stop toggle ---
    cmp #$21
    bne ml_check_r_down
    lda seq_playing
    bne ml_do_stop
    
    ; Start playing
    lda #$FF
    sta seq_playing
    jmp main_loop
    
ml_do_stop:
    ; Stop playing and silence all channels
    lda #0
    sta seq_playing
    sta trk0_active
    sta trk1_active
    sta trk2_active
    lda #SILENCE
    sta AUDC1
    sta AUDC2
    sta AUDC3
    jmp main_loop
    
ml_check_r_down:
    ; --- R key ($28) = restart ---
    cmp #$28
    bne ml_continue             ; Unknown key? Continue loop
    jsr seq_init                ; Reinitialize everything
    jmp main_loop

ml_check_release:
    ; --- Check for key release ---
    lda SKSTAT
    and #$04
    beq ml_continue             ; Still pressed? Continue
    lda SKSTAT                  ; Double-read for debounce
    and #$04  
    beq ml_continue
    
    ; Key released
    lda #$FF
    sta last_key_code
    ; Fall through to ml_continue

.else
    ; --- Minimal keyboard mode (KEY_CONTROL=0) ---
    ; Only check for SPACE when stopped, then no more keyboard checks
    lda seq_playing
    bne ml_continue             ; Already playing? Skip all keyboard (saves cycles!)
    
    ; Not playing - check for SPACE to start
    lda SKSTAT
    and #$04                    ; Bit 2 = key pressed
    bne ml_continue             ; No key? Continue loop
    
    lda KBCODE
    and #$3F
    cmp #$21                    ; SPACE key?
    bne ml_continue
    
    ; Start playing (one-shot - will play through song)
    lda #$FF
    sta seq_playing
    ; Fall through to ml_continue
.endif

ml_continue:
    ; Trampoline to main_loop - consolidates backward branches
    jmp main_loop

; ==========================================================================
; NMI STUB - Not used (we poll VCOUNT instead)
; ==========================================================================
nmi_stub:
    rti

; ==========================================================================
; INCLUDE SUBROUTINES
; ==========================================================================
    icl "tracker/parse_event.asm"       ; Event parsing (called 3x per row)
    icl "tracker/seq_init.asm"          ; Initialization
    icl "tracker/seq_load_songline.asm" ; Songline loading
    icl "tracker/update_display.asm"    ; Display update (conditional)

; ==========================================================================
; INCLUDE IRQ HANDLER (speed or size optimized)
; ==========================================================================
.if OPTIMIZE_SPEED = 1
    icl "tracker/tracker_irq_speed.asm" ; Full-byte VQ data (faster)
.else
    icl "tracker/tracker_irq_size.asm"  ; Nibble-packed VQ data (smaller)
.endif

; ==========================================================================
; INCLUDE DATA TABLES
; ==========================================================================
    icl "pitch/pitch_tables.asm"        ; NOTE_PITCH_LO/HI tables

.if OPTIMIZE_SPEED = 0
    icl "pitch/LUT_NIBBLES.asm"         ; Nibble extraction LUTs (size mode)
.endif

    icl "pitch/VOLUME_SCALE.asm"        ; Volume scaling table (conditional)
    icl "common/pokey_setup.asm"        ; POKEY initialization

; ==========================================================================
; INCLUDE SONG AND SAMPLE DATA
; ==========================================================================
    icl "SONG_DATA.asm"                 ; Song structure and patterns
    icl "SAMPLE_DIR.asm"                ; Sample pointers
    icl "VQ_LO.asm"                     ; VQ codebook low bytes
    icl "VQ_HI.asm"                     ; VQ codebook high bytes
    icl "VQ_BLOB.asm"                   ; VQ vector data
    icl "VQ_INDICES.asm"                ; VQ index streams

; ==========================================================================
; VOLUME CONTROL VARIABLE (not in zero-page)
; ==========================================================================
; trk2_vol_shift must be in regular memory because $BE-$BF are used
; for trk0/trk1 vol_shift, and we ran out of contiguous zero-page.
.if VOLUME_CONTROL = 1
trk2_vol_shift:   .byte $F0             ; Channel 2 volume (pre-shifted)
.endif

; ==========================================================================
; ENTRY POINT
; ==========================================================================
    run start
