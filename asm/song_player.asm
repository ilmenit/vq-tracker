; ==========================================================================
; SONG PLAYER - POKEY VQ Tracker
; ==========================================================================
; Version: 3.4
;
; Plays songs exported from the POKEY VQ Tracker GUI application.
;
; Features:
;   - 3-channel polyphonic playback via VQ-compressed samples
;   - Per-songline speed control
;   - Variable-length event encoding for compact pattern storage
;   - Keyboard control (Space=play/stop, R=restart)
;   - Optional volume control per note (VOLUME_CONTROL=1)
;   - Two IRQ modes: speed or size optimized (OPTIMIZE_SPEED)
;   - Optional blank screen mode for maximum CPU cycles (BLANK_SCREEN=1)
;
; Optimization Modes (set in SONG_CFG.asm):
;   OPTIMIZE_SPEED=1: Full bytes with $10 pre-baked
;                     ~63 cycles/channel (no boundary cross)
;                     ~125 cycles/channel (with boundary cross)
;                     Enables higher sample rates (7917 Hz)
;   OPTIMIZE_SPEED=0: Nibble-packed data
;                     ~83 cycles/channel (no boundary cross)
;                     ~145 cycles/channel (with boundary cross)
;                     Better for memory-constrained projects
;
; BLANK_SCREEN Mode (set in SONG_CFG.asm):
;   BLANK_SCREEN=0: Normal display with SONG/ROW/SPEED readout
;   BLANK_SCREEN=1: Display ON when stopped (shows instructions)
;                   Display OFF when playing (green screen, max CPU)
;                   Gains ~30% more CPU cycles for IRQ during playback
;
; Memory Map:
;   $2000+: Player code and data
;   $80-$BF: Zero page variables (see zeropage.inc)
;
; Timing Architecture:
;   - Timer IRQ: Sample playback (high frequency, e.g., 7917 Hz)
;   - VCOUNT polling: Sequencer timing at 50Hz (PAL)
;   - NMI is DISABLED to avoid IRQ/NMI race conditions
;     (NMI could corrupt IRQ registers mid-execution)
;
; ==========================================================================

    icl "common/atari.inc"
    
    ; Enable tracker mode for zero page layout
    TRACKER = 1
    icl "common/zeropage.inc" 
    icl "common/macros.inc"
    icl "common/copy_os_ram.asm"
    icl "VQ_CFG.asm"
    
    ; Include SONG_CFG.asm for VOLUME_CONTROL equate (needed for conditional assembly)
    ; NOTE: This file contains ONLY equates, no .byte data!
    ; The actual song data is in SONG_DATA.asm, included at the END with other data.
    icl "SONG_CFG.asm"
    
    ; === Configuration Defaults ===
    ; BLANK_SCREEN: Set to 1 to disable display and gain ~30% more CPU cycles
    .ifndef BLANK_SCREEN
        BLANK_SCREEN = 0    ; Default: display enabled
    .endif
    
    ; === Configuration Validation ===
    .ifndef MULTI_SAMPLE
        .error "song_player.asm requires MULTI_SAMPLE=1"
    .endif
    .ifndef PITCH_CONTROL
        .error "song_player.asm requires PITCH_CONTROL=1"
    .endif
    .ifndef ALGO_FIXED
        .error "song_player.asm requires ALGO_FIXED=1"
    .endif

    ORG $2000

; ==========================================================================
; CONSTANTS
; ==========================================================================
SILENCE     = $10               ; POKEY volume-only mode, volume=0

; ==========================================================================
; SEQUENCER STATE (Regular memory - not zero page)
; ==========================================================================
; Per-channel event pointers (current position in pattern data)
seq_evt_ptr_lo:   .byte 0,0,0   ; Low byte of event pointer
seq_evt_ptr_hi:   .byte 0,0,0   ; High byte of event pointer
seq_evt_row:      .byte $FF,$FF,$FF  ; Next event's row number ($FF=end)

; Pattern loop tracking (for different-length patterns)
seq_ptn_len:      .byte 64,64,64    ; Pattern length per channel
seq_local_row:    .byte 0,0,0       ; Local row within each pattern (0 to len-1)
seq_ptn_start_lo: .byte 0,0,0       ; Pattern start address (for reset on loop)
seq_ptn_start_hi: .byte 0,0,0       ; Pattern start address high byte

; Per-channel last values (for delta encoding)
seq_last_inst:    .byte 0,0,0   ; Last instrument per channel
seq_last_vol:     .byte 15,15,15 ; Last volume per channel

; Parsed event data (current row)
evt_note:         .byte 0,0,0   ; Note for each channel (0=none)
evt_inst:         .byte 0,0,0   ; Instrument for each channel
evt_vol:          .byte 0,0,0   ; Volume for each channel
evt_trigger:      .byte 0,0,0   ; Trigger flag ($FF=trigger note)

; VBLANK polling state (replaces NMI-based timing)
; Detects VCOUNT transition from high (>=128) to low (<128) = new frame
vcount_phase:     .byte 0       ; $00=low phase, $80=high phase

; ==========================================================================
; DISPLAY LIST 
; ==========================================================================
.if BLANK_SCREEN = 0
; --- NORMAL MODE: Full status display ---
; Each line must be exactly 40 characters for Atari text mode 2
text_line1:
;         1234567890123456789012345678901234567890
    dta d" VQ TRACKER - [SPACE] play, [R] reset   "
text_line2:
;        1234567890123456789012345678901234567890
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
    .byte $70,$70,$70           ; 3 blank lines
    .byte $42,<text_line1,>text_line1
    .byte $02                   ; Mode 2 text
    .byte $41,<dlist,>dlist     ; Jump back
.else
; --- BLANK SCREEN MODE: Display toggles based on play state ---
; When stopped: Display ON (DMACTL=34) - user sees instructions below
; When playing: Display OFF (DMACTL=0) - green screen, max CPU for IRQ
; This gains ~30% more CPU cycles during playback
text_line1:
;         1234567890123456789012345678901234567890
    dta d" VQ TRACKER - [SPACE] play, [R] reset   "
dlist:
    .byte $70,$70,$70           ; 3 blank lines
    .byte $42,<text_line1,>text_line1
    .byte $41,<dlist,>dlist     ; Jump back
.endif

; ==========================================================================
; MAIN ENTRY POINT
; ==========================================================================
start:
    sei
    ldx #$FF
    txs                         ; Reset stack
    
    ; Disable interrupts and DMA during setup
    lda #0
    sta NMIEN
    sta IRQEN
    sta DMACTL
    lda #$FE
    sta PORTB                   ; Enable RAM under ROM
    
    ; Setup interrupt vectors
    ; NMI points to minimal handler (just RTI) since we use polling instead
    lda #<nmi_stub
    sta $FFFA
    lda #>nmi_stub
    sta $FFFA+1
    
    lda #<Tracker_IRQ
    sta $FFFE
    lda #>Tracker_IRQ
    sta $FFFE+1
    
    ; Setup display
    lda #<dlist
    sta DLISTL
    lda #>dlist
    sta DLISTH
    
.if BLANK_SCREEN = 0
    ; --- NORMAL MODE: Enable display DMA ---
    lda #34                     ; Enable DMA (narrow playfield)
    sta DMACTL
.else
    ; --- BLANK SCREEN MODE: Display enabled when stopped, disabled when playing ---
    ; This gives maximum CPU cycles during playback while allowing user to see
    ; instructions when stopped. DMACTL is toggled in main loop based on seq_playing.
    lda #34
    sta DMACTL
.endif
    
    ; NMI disabled - we use polling instead to avoid IRQ/NMI race conditions
    ; NMI can corrupt IRQ's working registers mid-execution, causing audio glitches
    ; and register corruption visible as COLBK color stripes
    lda #$00                    ; Disable NMI completely
    sta NMIEN
    
    ; Initialize VCOUNT phase tracking for polling-based VBLANK detection
    lda VCOUNT
    and #$80                    ; Get current phase (bit 7)
    sta vcount_phase
    
    ; Init keyboard
    lda #0
    sta SKCTL
    lda #3
    sta SKCTL
    
    ; Initialize sequencer and audio
    jsr seq_init
    jsr Pokey_Setup
    
    ; Enable timer IRQ
    lda #IRQ_MASK
    sta IRQEN
    lda #$00
    sta STIMER
    
    cli

; ==========================================================================
; MAIN LOOP - Keyboard handling, VBLANK polling, status display
; ==========================================================================
; VBLANK is detected by polling VCOUNT instead of using NMI.
; This eliminates the IRQ/NMI race condition that caused register corruption.
;
; VCOUNT behavior (PAL):
;   Scanlines 0-255:   VCOUNT = 0-127  (bit 7 = 0) - active display
;   Scanlines 256-311: VCOUNT = 128-155 (bit 7 = 1) - VBLANK region
;   Then wraps to 0
;
; We detect the transition from high (bit7=1) to low (bit7=0) = new frame
; ==========================================================================
main_loop:
    ; === VBLANK POLLING (replaces NMI) ===
    ; Check for VCOUNT phase transition
    lda VCOUNT
    and #$80                    ; Get bit 7 (phase indicator): $00 or $80
    tax                         ; Save phase in X (preserves A)
    cmp vcount_phase
    beq ml_no_vblank            ; Same phase, no transition
    
    ; Phase changed! Update tracking
    stx vcount_phase
    
    ; Check if this is high->low transition (new frame)
    ; TXA sets Z flag based on X: Z=1 if X=$00, Z=0 if X=$80
    txa                         ; A=X, and SETS FLAGS based on value
    bne ml_no_vblank            ; If A=$80, we entered VBLANK, wait for exit
    
    ; === NEW FRAME (A=$00) - Run sequencer tick ===
    lda seq_playing
    beq ml_skip_seq
    
    inc seq_tick
    lda seq_tick
    cmp seq_speed
    bcc ml_skip_seq
    
    ; Time for next row
    lda #0
    sta seq_tick
    jsr process_row
    
ml_skip_seq:
.if BLANK_SCREEN = 0
    jsr update_display
.endif

ml_no_vblank:
    ; === Visual feedback ===
    ; NOTE: If you see color stripes here, it indicates register corruption!
    lda seq_playing
    beq ml_idle_state
    
    ; --- PLAYING ---
    lda #$40                    ; Green background
.if BLANK_SCREEN = 1
    ldx #0                      ; DMACTL = 0 (display off for max CPU)
.endif
    bne ml_set_state            ; Always taken (A=$40)
    
ml_idle_state:
    ; --- STOPPED ---
    lda #$20                    ; Dark gray background
.if BLANK_SCREEN = 1
    ldx #34                     ; DMACTL = 34 (display on to show instructions)
.endif

ml_set_state:
    sta COLBK
.if BLANK_SCREEN = 1
    stx DMACTL
.endif
    
    ; === Keyboard State Machine ===
    ; last_key_code: $FF = waiting for keydown, other = key held
    ; SKSTAT bit 2: 0 = key pressed, 4 = no key
    
    lda last_key_code
    cmp #$FF
    bne ml_check_release        ; Key held, check for release
    
    ; --- Waiting for keydown ---
    lda SKSTAT
    and #$04
    bne main_loop               ; No key pressed
    ; Double-check (debounce)
    lda SKSTAT
    and #$04
    bne main_loop
    
    ; Key pressed - read and process
    lda KBCODE
    and #$3F
    sta last_key_code
    
    ; Check SPACE (play/stop)
    cmp #$21
    bne ml_check_r_down
    lda seq_playing
    bne ml_do_stop
    lda #$FF
    sta seq_playing
    jmp main_loop
ml_do_stop:
    jsr seq_stop
    jmp main_loop
    
    ; Check R (restart)
ml_check_r_down:
    cmp #$28
    bne main_loop
    jsr seq_init
    jmp main_loop

ml_check_release:
    ; --- Key held, check for release ---
    lda SKSTAT
    and #$04
    beq main_loop               ; Still pressed
    lda SKSTAT
    and #$04  
    beq main_loop               ; Debounce
    
    ; Key released
    lda #$FF
    sta last_key_code
    jmp main_loop

; ==========================================================================
; NMI STUB - Minimal handler since we use polling instead
; ==========================================================================
; NMI is disabled (NMIEN=0) but we need a handler just in case.
; The sequencer now runs via VCOUNT polling in main_loop to avoid
; the IRQ/NMI race condition that caused register corruption.
; ==========================================================================
nmi_stub:
    rti

; ==========================================================================
; PROCESS_ROW - Parse events and trigger notes
; ==========================================================================
; Each channel tracks its own local row within its pattern.
; Shorter patterns loop when they reach their end.
; ==========================================================================
process_row:
    ; Clear trigger flags
    lda #0
    sta evt_trigger
    sta evt_trigger+1
    sta evt_trigger+2
    
    ; Parse each channel if event matches LOCAL row (not global seq_row)
    lda seq_evt_row
    cmp seq_local_row           ; Compare with channel 0's local row
    bne pr_no_ch0
    ldx #0
    jsr parse_event
    lda #$FF
    sta evt_trigger
pr_no_ch0:

    lda seq_evt_row+1
    cmp seq_local_row+1         ; Compare with channel 1's local row
    bne pr_no_ch1
    ldx #1
    jsr parse_event
    lda #$FF
    sta evt_trigger+1
pr_no_ch1:

    lda seq_evt_row+2
    cmp seq_local_row+2         ; Compare with channel 2's local row
    bne pr_no_ch2
    ldx #2
    jsr parse_event
    lda #$FF
    sta evt_trigger+2
pr_no_ch2:

    ; Trigger notes with IRQ disabled
    sei
    
    ldx #0
    lda evt_trigger
    beq pr_no_trig0
    jsr trigger_note
pr_no_trig0:

    ldx #1
    lda evt_trigger+1
    beq pr_no_trig1
    jsr trigger_note
pr_no_trig1:

    ldx #2
    lda evt_trigger+2
    beq pr_no_trig2
    jsr trigger_note
pr_no_trig2:

    cli
    
    ; === Advance local rows and check for pattern wrap ===
    ldx #2
pr_advance_local:
    inc seq_local_row,x
    lda seq_local_row,x
    cmp seq_ptn_len,x
    bcc pr_no_wrap              ; local_row < ptn_len, no wrap needed
    
    ; Pattern reached end - reset to beginning
    lda #0
    sta seq_local_row,x
    
    ; Reset event pointer to pattern start
    lda seq_ptn_start_lo,x
    sta seq_evt_ptr_lo,x
    lda seq_ptn_start_hi,x
    sta seq_evt_ptr_hi,x
    
    ; Reload first event's row number
    sta seq_ptr+1
    lda seq_ptn_start_lo,x
    sta seq_ptr
    stx parse_temp              ; Save X
    ldy #0
    lda (seq_ptr),y
    ldx parse_temp              ; Restore X
    sta seq_evt_row,x
    
pr_no_wrap:
    dex
    bpl pr_advance_local
    
    ; Advance global row counter
    inc seq_row
    lda seq_row
    cmp seq_max_len
    bcc pr_done
    
    ; End of pattern - advance songline
    lda #0
    sta seq_row
    
    inc seq_songline
    lda seq_songline
    cmp #SONG_LENGTH            ; Use immediate mode for equate comparison
    bcc pr_load_new
    
    ; End of song - loop back
    lda #0
    sta seq_songline
    
pr_load_new:
    jsr seq_load_songline
    
pr_done:
    rts

; ==========================================================================
; PARSE_EVENT - Read variable-length event data
; ==========================================================================
; Input: X = channel (0-2)
; Reads from seq_evt_ptr and advances pointer
;
; Event format:
;   BYTE 0: row number
;   BYTE 1: note (bits 0-5) + flags (bits 6-7)
;   BYTE 2: [optional] instrument + flag
;   BYTE 3: [optional] volume
; ==========================================================================
parse_event:
    stx parse_channel
    
    ; Setup pointer
    lda seq_evt_ptr_lo,x
    sta seq_ptr
    lda seq_evt_ptr_hi,x
    sta seq_ptr+1
    
    ; Read note byte (offset 1, skip row at offset 0)
    ldy #1
    lda (seq_ptr),y
    sta parse_temp
    and #$3F                    ; Extract note (bits 0-5)
    ldx parse_channel
    sta evt_note,x
    iny
    
    ; Check instrument flag (bit 7)
    lda parse_temp
    bpl pe_use_last             ; No instrument follows
    
    ; Read instrument
    lda (seq_ptr),y
    sta parse_temp
    and #$7F                    ; Extract instrument (bits 0-6)
    ldx parse_channel
    sta evt_inst,x
    sta seq_last_inst,x
    iny
    
    ; Check volume flag (bit 7 of instrument byte)
    lda parse_temp
    bpl pe_use_last_vol         ; No volume follows
    
    ; Read volume
    lda (seq_ptr),y
    and #$0F                    ; Extract volume (bits 0-3)
    ldx parse_channel
    sta evt_vol,x
    sta seq_last_vol,x
    iny
    jmp pe_advance
    
pe_use_last_vol:
    ldx parse_channel
    lda seq_last_vol,x
    sta evt_vol,x
    jmp pe_advance
    
pe_use_last:
    ldx parse_channel
    lda seq_last_inst,x
    sta evt_inst,x
    lda seq_last_vol,x
    sta evt_vol,x
    
pe_advance:
    ; Advance pointer by Y bytes
    ldx parse_channel
    tya
    clc
    adc seq_evt_ptr_lo,x
    sta seq_evt_ptr_lo,x
    bcc pe_no_carry
    inc seq_evt_ptr_hi,x
pe_no_carry:

    ; Load next event's row number
    lda seq_evt_ptr_lo,x
    sta seq_ptr
    lda seq_evt_ptr_hi,x
    sta seq_ptr+1
    ldy #0
    lda (seq_ptr),y
    sta seq_evt_row,x
    rts

; ==========================================================================
; TRIGGER_NOTE - Play note on channel
; ==========================================================================
; Input: X = channel (0-2)
; Uses evt_note, evt_inst, evt_vol arrays
;
; Note encoding:
;   GUI note 1 (C-1) -> pitch index 0 -> 1.0x speed
;   GUI note 13 (C-2) -> pitch index 12 -> 2.0x speed
;   GUI note 25 (C-3) -> pitch index 24 -> 4.0x speed
; ==========================================================================
trigger_note:
    lda evt_note,x
    beq tn_note_off             ; Note 0 = note off
    
    stx parse_channel
    
    ; Convert GUI note (1-36) to pitch table index (0-35)
    sec
    sbc #1
    sta parse_temp
    
.if VOLUME_CONTROL = 1
    ; Set volume for this channel (vol * 16 for LUT indexing)
    ldx parse_channel
    lda evt_vol,x
    asl                         ; vol * 2
    asl                         ; vol * 4
    asl                         ; vol * 8
    asl                         ; vol * 16
    
    ; Store in appropriate channel volume variable
    cpx #0
    bne @tn_not_vol0
    sta trk0_vol_shift
    jmp @tn_vol_done
@tn_not_vol0:
    cpx #1
    bne @tn_not_vol1
    sta trk1_vol_shift
    jmp @tn_vol_done
@tn_not_vol1:
    sta trk2_vol_shift
@tn_vol_done:
.endif
    
    ; Get instrument
    ldx parse_channel
    lda evt_inst,x
    and #$7F
    
    ; Call Tracker_PlayNote: A=sample, X=note, Y=channel
    ldx parse_temp
    ldy parse_channel
    jmp Tracker_PlayNote

tn_note_off:
    ; Silence the channel
    cpx #0
    bne tn_not_ch0
    lda #0
    sta trk0_active
    lda #SILENCE
    sta AUDC1
    rts
tn_not_ch0:
    cpx #1
    bne tn_not_ch1
    lda #0
    sta trk1_active
    lda #SILENCE
    sta AUDC2
    rts
tn_not_ch1:
    lda #0
    sta trk2_active
    lda #SILENCE
    sta AUDC3
    rts

; ==========================================================================
; SEQ_INIT - Initialize sequencer to beginning of song
; ==========================================================================
seq_init:
    lda #0
    sta seq_songline
    sta seq_row
    sta seq_tick
    sta seq_playing
    
    lda #6                      ; Default speed
    sta seq_speed
    lda #64                     ; Default pattern length
    sta seq_max_len
    lda #$FF
    sta last_key_code
    
    ; Initialize per-channel state
    ldx #2
si_loop:
    lda #0
    sta seq_last_inst,x
    sta evt_trigger,x
    sta seq_local_row,x         ; Initialize local row counter
    lda #$FF
    sta seq_evt_row,x
    lda #15
    sta seq_last_vol,x
    lda #64
    sta seq_ptn_len,x           ; Default pattern length
    dex
    bpl si_loop
    
.if VOLUME_CONTROL = 1
    ; Initialize volume shift values to max (15 * 16 = $F0)
    lda #$F0
    sta trk0_vol_shift
    sta trk1_vol_shift
    sta trk2_vol_shift
.endif
    
    ; Silence all channels
    lda #0
    sta trk0_active
    sta trk1_active
    sta trk2_active
    lda #SILENCE
    sta AUDC1
    sta AUDC2
    sta AUDC3
    
    jsr seq_load_songline
    rts

; ==========================================================================
; SEQ_STOP - Stop playback
; ==========================================================================
seq_stop:
    lda #0
    sta seq_playing
    sta trk0_active
    sta trk1_active
    sta trk2_active
    lda #SILENCE
    sta AUDC1
    sta AUDC2
    sta AUDC3
    rts

; ==========================================================================
; SEQ_LOAD_SONGLINE - Load patterns for current songline
; ==========================================================================
; Initializes all three channels with their pattern data.
; Stores pattern length and start address for loop handling.
; ==========================================================================
seq_load_songline:
    ldx seq_songline
    
    ; Get speed for this songline
    lda SONG_SPEED,x
    sta seq_speed
    
    ; Reset row positions
    lda #0
    sta seq_row
    sta seq_max_len
    sta seq_local_row           ; Reset channel 0 local row
    sta seq_local_row+1         ; Reset channel 1 local row
    sta seq_local_row+2         ; Reset channel 2 local row
    
    ; === Channel 0 ===
    lda SONG_PTN_CH0,x
    tay
    
    ; Store pattern length
    lda PATTERN_LEN,y
    sta seq_ptn_len             ; Store for channel 0
    cmp seq_max_len
    bcc sls_no_max0
    sta seq_max_len
sls_no_max0:

    ; Store pattern start address
    lda PATTERN_PTR_LO,y
    sta seq_ptn_start_lo        ; Store start for looping
    sta seq_evt_ptr_lo          ; Current position = start
    lda PATTERN_PTR_HI,y
    sta seq_ptn_start_hi        ; Store start for looping
    sta seq_evt_ptr_hi          ; Current position = start
    
    ; Load first event's row
    sta seq_ptr+1
    lda seq_ptn_start_lo
    sta seq_ptr
    ldy #0
    lda (seq_ptr),y
    sta seq_evt_row
    
    ; === Channel 1 ===
    ldx seq_songline
    lda SONG_PTN_CH1,x
    tay
    
    ; Store pattern length
    lda PATTERN_LEN,y
    sta seq_ptn_len+1           ; Store for channel 1
    cmp seq_max_len
    bcc sls_no_max1
    sta seq_max_len
sls_no_max1:

    ; Store pattern start address
    lda PATTERN_PTR_LO,y
    sta seq_ptn_start_lo+1      ; Store start for looping
    sta seq_evt_ptr_lo+1        ; Current position = start
    lda PATTERN_PTR_HI,y
    sta seq_ptn_start_hi+1      ; Store start for looping
    sta seq_evt_ptr_hi+1        ; Current position = start
    
    ; Load first event's row
    sta seq_ptr+1
    lda seq_ptn_start_lo+1
    sta seq_ptr
    ldy #0
    lda (seq_ptr),y
    sta seq_evt_row+1
    
    ; === Channel 2 ===
    ldx seq_songline
    lda SONG_PTN_CH2,x
    tay
    
    ; Store pattern length
    lda PATTERN_LEN,y
    sta seq_ptn_len+2           ; Store for channel 2
    cmp seq_max_len
    bcc sls_no_max2
    sta seq_max_len
sls_no_max2:

    ; Store pattern start address
    lda PATTERN_PTR_LO,y
    sta seq_ptn_start_lo+2      ; Store start for looping
    sta seq_evt_ptr_lo+2        ; Current position = start
    lda PATTERN_PTR_HI,y
    sta seq_ptn_start_hi+2      ; Store start for looping
    sta seq_evt_ptr_hi+2        ; Current position = start
    
    ; Load first event's row
    sta seq_ptr+1
    lda seq_ptn_start_lo+2
    sta seq_ptr
    ldy #0
    lda (seq_ptr),y
    sta seq_evt_row+2
    
    ; Reset last values for new patterns
    ldx #2
sls_reset_last:
    lda #0
    sta seq_last_inst,x
    lda #15
    sta seq_last_vol,x
    dex
    bpl sls_reset_last
    
    rts

; ==========================================================================
; UPDATE_DISPLAY - Update on-screen status
; ==========================================================================
.if BLANK_SCREEN = 0
update_display:
    ; Update songline display
    lda seq_songline
    jsr byte_to_dec
    stx song_pos_display        ; X = tens (left digit)
    sta song_pos_display+1      ; A = ones (right digit)
    
    ; Update row display
    lda seq_row
    jsr byte_to_dec
    stx row_display             ; X = tens (left digit)
    sta row_display+1           ; A = ones (right digit)
    
    ; Update speed display
    lda seq_speed
    jsr byte_to_dec
    stx speed_display           ; X = tens (left digit)
    sta speed_display+1         ; A = ones (right digit)
    rts

; Convert A to 2-digit decimal for screen display
; Input:  A = value (0-99)
; Output: X = tens digit (screen code), A = ones digit (screen code)
byte_to_dec:
    ldx #0
btd_loop:
    cmp #10
    bcc btd_done
    sec
    sbc #10
    inx
    jmp btd_loop
btd_done:
    ; A = ones (0-9), X = tens (0-9)
    clc
    adc #$10                    ; Convert ones to screen code '0'-'9'
    pha                         ; Save ones
    txa                         ; A = tens
    clc
    adc #$10                    ; Convert tens to screen code
    tax                         ; X = tens (screen code)
    pla                         ; A = ones (screen code)
    rts
.endif

; ==========================================================================
; INCLUDE MODULES
; ==========================================================================
    icl "tracker/tracker_api.asm"
    
    ; Select IRQ handler based on VQ optimization mode
.if OPTIMIZE_SPEED = 1
    ; Speed mode: full bytes with $10 pre-baked, direct load/store
    icl "tracker/tracker_irq_speed.asm"
.else
    ; Size mode: nibble-packed data, requires LUT unpacking
    icl "tracker/tracker_irq_size.asm"
.endif

; ==========================================================================
; INCLUDE DATA
; ==========================================================================
    icl "pitch/pitch_tables.asm"
    
    ; LUT_NIBBLES only needed for size mode (nibble unpacking)
.if OPTIMIZE_SPEED = 0
    icl "pitch/LUT_NIBBLES.asm"
.endif

    icl "pitch/VOLUME_SCALE.asm"
    icl "common/pokey_setup.asm"

    ; Song data - MUST be included here (after code) to avoid being overwritten!
    ; SONG_CFG.asm was included early for the VOLUME_CONTROL equate.
    icl "SONG_DATA.asm"

    icl "SAMPLE_DIR.asm"
    icl "VQ_LO.asm"
    icl "VQ_HI.asm"
    icl "VQ_BLOB.asm"
    icl "VQ_INDICES.asm"

; ==========================================================================
; VOLUME CONTROL VARIABLES (when VOLUME_CONTROL=1)
; ==========================================================================
; Channel 2 volume stored in regular memory (no ZP space left)
.if VOLUME_CONTROL = 1
trk2_vol_shift:   .byte $F0     ; Volume * 16 (default = max)
.endif

    run start
