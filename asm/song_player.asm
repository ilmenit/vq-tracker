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
;   - Two IRQ modes: speed or size optimized (OPTIMIZE_SPEED)
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
; DISPLAY LIST AND TEXT
; ==========================================================================
.if BLANK_SCREEN = 0
; --- Normal display: 2 text lines (always visible) ---
.if KEY_CONTROL = 1
text_line1:
    dta d"VQ TRACKER - [SPACE] play/stop [R] reset"  ; 40 chars
.else
text_line1:
    dta d"   VQ TRACKER - [SPACE] to play         "  ; 40 chars
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
    .byte $42,<text_line1,>text_line1  ; Mode 2 text line 1
    .byte $02                   ; Mode 2 text line 2 (continues from prev)
    .byte $41,<dlist,>dlist     ; Jump and wait for VBL
.else
; --- Blank screen mode: display visible when stopped, blank when playing ---
.if KEY_CONTROL = 1
text_line1:
    dta d"VQ TRACKER - [SPACE] play/stop [R] reset"  ; 40 chars
.else
text_line1:
    dta d"   VQ TRACKER - [SPACE] to play         "  ; 40 chars
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
    .byte $42,<text_line1,>text_line1  ; Mode 2 text line 1
    .byte $02                   ; Mode 2 text line 2
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
; PROCESS ROW - Placed before main_loop for short branch distances
; ==========================================================================
do_process_row:
    icl "tracker/process_row.asm"
    jmp ml_check_state_change   ; Return to main loop after processing

; ==========================================================================
; MAIN LOOP
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
    lda seq_playing
    beq ml_check_state_change   ; Not playing? Skip
    
    ; --- Tick counter ---
    inc seq_tick
    lda seq_tick
    cmp seq_speed
    bcc ml_check_state_change   ; Not time for new row
    
    ; --- New row ---
    lda #0
    sta seq_tick
    jmp do_process_row
    
ml_check_state_change:
    ; --- Handle play/stop transitions ---
    lda seq_playing
    cmp last_playing
    beq ml_state_done
    
    sta last_playing
    beq ml_now_stopped
    
    ; --- Started playing ---
.if BLANK_SCREEN = 1
    ldx #0
    stx DMACTL                  ; Disable display DMA for max CPU
.endif
    lda #COL_PLAYING
    bne ml_set_color            ; Always branches (COL_PLAYING=$74, Z=0)
    
ml_now_stopped:
.if BLANK_SCREEN = 1
    ldx #$22
    stx DMACTL                  ; Re-enable display DMA
.endif
    lda #COL_STOPPED

ml_set_color:
    sta COLBK

ml_state_done:
.if BLANK_SCREEN = 1
    lda seq_playing
    bne ml_no_vblank            ; Skip display update while playing (screen is off)
.endif
    jsr update_display

ml_no_vblank:
    ; =====================================================================
    ; KEYBOARD HANDLING
    ; =====================================================================

.if KEY_CONTROL = 1
    ; --- Full keyboard control mode ---
    lda last_key_code
    cmp #$FF
    bne ml_check_release        ; Key still held? Check for release
    
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
    ; Stop playing and silence all 4 channels
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
    jmp main_loop
    
ml_check_r_down:
    ; --- R key ($28) = restart ---
    cmp #$28
    bne ml_continue
    jsr seq_init
    jmp main_loop

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
    ; Fall through to ml_continue

.else
    ; --- Minimal keyboard mode (KEY_CONTROL=0) ---
    lda seq_playing
    bne ml_continue             ; Already playing? Skip keyboard
    
    lda SKSTAT
    and #$04
    bne ml_continue
    
    lda KBCODE
    and #$3F
    cmp #$21                    ; SPACE key?
    bne ml_continue
    
    lda #$FF
    sta seq_playing
.endif

ml_continue:
    jmp main_loop

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
; INCLUDE IRQ HANDLER
; ==========================================================================
.if OPTIMIZE_SPEED = 1
    icl "tracker/tracker_irq_speed.asm"
.else
    icl "tracker/tracker_irq_size.asm"
.endif

; ==========================================================================
; INCLUDE DATA TABLES
; ==========================================================================
    icl "pitch/pitch_tables.asm"

.if OPTIMIZE_SPEED = 0
    icl "pitch/LUT_NIBBLES.asm"
.endif

    icl "pitch/VOLUME_SCALE.asm"

; ==========================================================================
; INCLUDE SONG AND SAMPLE DATA
; ==========================================================================
    icl "SONG_DATA.asm"
    icl "SAMPLE_DIR.asm"
    icl "VQ_LO.asm"
    icl "VQ_HI.asm"
    icl "VQ_BLOB.asm"
    icl "VQ_INDICES.asm"

; ==========================================================================
; STAGING AREA - Regular memory (used at row rate only, not IRQ rate)
; ==========================================================================
; Channel 0 staging
prep0_pitch_lo:   .byte 0
prep0_pitch_hi:   .byte 0
prep0_stream_lo:  .byte 0
prep0_stream_hi:  .byte 0
prep0_end_lo:     .byte 0
prep0_end_hi:     .byte 0
prep0_vq_lo:      .byte 0
prep0_vq_hi:      .byte 0
; Channel 1 staging
prep1_pitch_lo:   .byte 0
prep1_pitch_hi:   .byte 0
prep1_stream_lo:  .byte 0
prep1_stream_hi:  .byte 0
prep1_end_lo:     .byte 0
prep1_end_hi:     .byte 0
prep1_vq_lo:      .byte 0
prep1_vq_hi:      .byte 0
; Channel 2 staging
prep2_pitch_lo:   .byte 0
prep2_pitch_hi:   .byte 0
prep2_stream_lo:  .byte 0
prep2_stream_hi:  .byte 0
prep2_end_lo:     .byte 0
prep2_end_hi:     .byte 0
prep2_vq_lo:      .byte 0
prep2_vq_hi:      .byte 0
; Channel 3 staging
prep3_pitch_lo:   .byte 0
prep3_pitch_hi:   .byte 0
prep3_stream_lo:  .byte 0
prep3_stream_hi:  .byte 0
prep3_end_lo:     .byte 0
prep3_end_hi:     .byte 0
prep3_vq_lo:      .byte 0
prep3_vq_hi:      .byte 0

; ==========================================================================
; VOLUME CONTROL VARIABLES (not in zero-page)
; ==========================================================================
.if VOLUME_CONTROL = 1
prep0_vol:        .byte $F0
prep1_vol:        .byte $F0
prep2_vol:        .byte $F0
prep3_vol:        .byte $F0
trk2_vol_shift:   .byte $F0    ; Channel 2 volume (pre-shifted)
trk3_vol_shift:   .byte $F0    ; Channel 3 volume (pre-shifted)
.endif

; ==========================================================================
; ENTRY POINT
; ==========================================================================
    run start
