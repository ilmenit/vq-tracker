; ==========================================================================
; SONG PLAYER - Atari 6502 Tracker (Optimized)
; ==========================================================================
;
; Plays songs exported from the Music Tracker application.
; 3-channel polyphonic playback with per-songline speed control.
; Uses variable-length event encoding for compact pattern data.
;
; OPTIMIZATIONS:
;   - Zero-page saves instead of stack (faster)
;   - Separated event parsing from note triggering for sample alignment
;   - Tight trigger loop minimizes timing skew between channels
;   - Inlined single-use subroutines where beneficial
;
; ARCHITECTURE:
;   - NMI (VBLANK): Sequencer timing, advances rows at speed rate
;   - IRQ (Timer): Sample playback via Tracker_IRQ (high frequency)
;   - Main loop: Keyboard handling, display updates
;
; EVENT FORMAT (Variable-Length):
;   Byte 0: row     - Row number (0-254), $FF = end of pattern
;   Byte 1: note    - Bit 7: inst follows, Bits 0-5: note (0=off, 1-36=C1-B3)
;   Byte 2: [inst]  - Optional. Bit 7: vol follows, Bits 0-6: instrument
;   Byte 3: [vol]   - Optional. Bits 0-3: volume (0-15)
;
; Requirements: MULTI_SAMPLE=1, PITCH_CONTROL=1, ALGO_FIXED=1 in VQ_CFG.asm
; Hardware: POKEY channels 1-3 (AUDC1, AUDC2, AUDC3)
;
; ==========================================================================

    icl "common/atari.inc"
    
    TRACKER = 1
    icl "common/zeropage.inc" 
    icl "common/macros.inc"
    icl "common/copy_os_ram.asm"
    icl "VQ_CFG.asm"
    
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
; SEQUENCER STATE (Main RAM)
; ==========================================================================
seq_songline:     .byte 0       ; Current songline index (0-255)
seq_row:          .byte 0       ; Current row within patterns (0-254)
seq_tick:         .byte 0       ; Tick counter (0 to speed-1)
seq_speed:        .byte 6       ; Current speed (VBLANKs per row)
seq_max_len:      .byte 64      ; Max pattern length for current songline
seq_playing:      .byte 0       ; Playback state: $FF=playing, $00=stopped

; --- Per-Channel Event Pointers ---
; These point to the NEXT event to check in each channel's pattern data
seq_evt_ptr_lo:   .byte 0,0,0   ; Event pointer low byte  [CH0, CH1, CH2]
seq_evt_ptr_hi:   .byte 0,0,0   ; Event pointer high byte [CH0, CH1, CH2]
seq_evt_row:      .byte 0,0,0   ; Row of next event ($FF = no more events)

; --- Per-Channel Last Values (for variable-length decoding) ---
seq_last_inst:    .byte 0,0,0   ; Last instrument per channel
seq_last_vol:     .byte 15,15,15 ; Last volume per channel (default=max)

; --- Parsed Event Data (filled by parse, used by trigger) ---
; Separate storage for each channel allows batch triggering
evt_note:         .byte 0,0,0   ; Parsed note (0=off, 1-48=note) [CH0,CH1,CH2]
evt_inst:         .byte 0,0,0   ; Parsed instrument [CH0,CH1,CH2]
evt_vol:          .byte 0,0,0   ; Parsed volume [CH0,CH1,CH2]
evt_trigger:      .byte 0,0,0   ; Trigger flags: $FF=trigger, $00=skip

; --- Zero-Page Temporaries (faster than stack) ---
zp_save_a:        .byte 0       ; NMI register save
zp_save_x:        .byte 0
zp_save_y:        .byte 0
zp_temp:          .byte 0       ; General temp
zp_channel:       .byte 0       ; Current channel being processed

; ==========================================================================
; DISPLAY LIST
; ==========================================================================
text_line1:
    dta d"   ATARI SAMPLE TRACKER   "
text_line2:
    dta d"SONG:"
song_pos_display:
    dta d"00"
    dta d" ROW:"
row_display:
    dta d"00"
    dta d" SPD:"
speed_display:
    dta d"06"
    dta d"      "
text_line3:
    dta d" SPACE=PLAY/STOP  R=RESET "

dlist:
    .byte $70,$70,$70                       ; 3 blank lines
    .byte $42,<text_line1,>text_line1       ; Mode 2 + LMS
    .byte $70
    .byte $42,<text_line2,>text_line2
    .byte $70
    .byte $42,<text_line3,>text_line3
    .byte $70,$70
    .byte $41,<dlist,>dlist                 ; JVB

; ==========================================================================
; MAIN ENTRY POINT
; ==========================================================================
start:
    sei
    ldx #$FF
    txs
    
    ; --- Disable OS ---
    lda #0
    sta NMIEN
    sta IRQEN
    sta DMACTL
    lda #$FE                    ; RAM under OS ROMs
    sta PORTB
    
    ; --- Setup Interrupt Vectors ---
    lda #<nmi_handler
    sta $FFFA
    lda #>nmi_handler
    sta $FFFA+1
    
    lda #<Tracker_IRQ
    sta $FFFE
    lda #>Tracker_IRQ
    sta $FFFE+1

    ; --- Setup Display ---
    lda #<dlist
    sta DLISTL
    lda #>dlist
    sta DLISTH
    lda #34                     ; Enable DMA, normal playfield
    sta DMACTL
    lda #$C0                    ; Enable VBI + DLI
    sta NMIEN
    
    ; --- Init Keyboard ---
    lda #0
    sta SKCTL
    lda #3
    sta SKCTL
    
    ; --- Init Sequencer ---
    jsr seq_init
    
    ; --- Init POKEY ---
    jsr Pokey_Setup
    
    ; --- Enable Timer IRQ ---
    lda #IRQ_MASK
    sta IRQEN
    lda #$00
    sta STIMER
    
    cli

; ==========================================================================
; MAIN LOOP - Keyboard & Display
; ==========================================================================
main_loop:
    ; --- Update Background Color (playing indicator) ---
    lda seq_playing
    beq @idle_color
    lda #$40                    ; Green = playing
    jmp @set_color
@idle_color:
    lda #$20                    ; Dark = stopped
@set_color:
    sta COLBK
    
    ; --- Check Keyboard ---
    lda SKSTAT
    and #4                      ; Key pressed?
    beq main_loop
    
    lda KBCODE
    and #$3F                    ; Remove shift/ctrl bits
    
    ; SPACE = Play/Stop toggle
    cmp #$21
    bne @check_r
    jsr debounce_key
    lda seq_playing
    bne @do_stop
    ; Start playing
    lda #$FF
    sta seq_playing
    jmp main_loop
@do_stop:
    jsr seq_stop
    jmp main_loop
    
    ; R = Reset to beginning
@check_r:
    cmp #$28
    bne main_loop
    jsr debounce_key
    jsr seq_init
    jmp main_loop

; --- Wait for key release ---
debounce_key:
@wait:
    lda SKSTAT
    and #4
    bne @wait
    rts

; ==========================================================================
; NMI HANDLER - VBLANK Sequencer Timing
; ==========================================================================
; Called 50/60 times per second. Advances song position based on speed.
; Uses zero-page saves instead of stack for speed.
; ==========================================================================
nmi_handler:
    ; --- Save Registers (ZP faster than stack) ---
    sta zp_save_a
    stx zp_save_x
    sty zp_save_y
    
    ; --- Check if Playing ---
    lda seq_playing
    beq @nmi_exit
    
    ; --- Tick Counter ---
    inc seq_tick
    lda seq_tick
    cmp seq_speed
    bcc @nmi_exit               ; tick < speed, wait
    
    ; --- Process Row (tick >= speed) ---
    lda #0
    sta seq_tick
    
    ; =========================================================
    ; INLINED: seq_process_row
    ; =========================================================
    ; Phase 1: Parse Events for All Channels
    ; Parsing is done BEFORE triggering to minimize trigger latency
    ; =========================================================
    
    lda #0
    sta evt_trigger             ; Clear trigger flags
    sta evt_trigger+1
    sta evt_trigger+2
    
    ; --- Parse Channel 0 ---
    lda seq_evt_row
    cmp seq_row
    bne @skip_parse_0
    ldx #0
    jsr parse_event
    lda #$FF
    sta evt_trigger
@skip_parse_0:

    ; --- Parse Channel 1 ---
    lda seq_evt_row+1
    cmp seq_row
    bne @skip_parse_1
    ldx #1
    jsr parse_event
    lda #$FF
    sta evt_trigger+1
@skip_parse_1:

    ; --- Parse Channel 2 ---
    lda seq_evt_row+2
    cmp seq_row
    bne @skip_parse_2
    ldx #2
    jsr parse_event
    lda #$FF
    sta evt_trigger+2
@skip_parse_2:

    ; =========================================================
    ; Phase 2: Trigger All Notes
    ; Tight loop with minimal code between triggers keeps
    ; samples synchronized across channels
    ; =========================================================
    
    sei                         ; Disable IRQ during trigger batch
    
    lda evt_trigger
    beq @no_trig_0
    ldx #0
    jsr trigger_note
@no_trig_0:

    lda evt_trigger+1
    beq @no_trig_1
    ldx #1
    jsr trigger_note
@no_trig_1:

    lda evt_trigger+2
    beq @no_trig_2
    ldx #2
    jsr trigger_note
@no_trig_2:

    cli                         ; Re-enable IRQ
    
    ; =========================================================
    ; Phase 3: Advance Row Counter
    ; =========================================================
    
    inc seq_row
    lda seq_row
    cmp seq_max_len
    bcc @nmi_exit               ; Still within pattern
    
    ; --- End of Pattern: Advance Songline ---
    lda #0
    sta seq_row
    
    inc seq_songline
    lda seq_songline
    cmp SONG_LENGTH
    bcc @load_new_songline
    
    ; --- End of Song: Loop ---
    lda #0
    sta seq_songline
    
@load_new_songline:
    jsr seq_load_songline
    
@nmi_exit:
    ; --- Update Display ---
    jsr update_display
    
    ; --- Restore Registers ---
    lda zp_save_a
    ldx zp_save_x
    ldy zp_save_y
    rti

; ==========================================================================
; PARSE_EVENT - Decode Variable-Length Event Data
; ==========================================================================
; Decodes the variable-length event at current pointer position.
; Advances pointer to next event and loads its row number.
;
; Input:  X = channel (0-2)
; Output: evt_note[X], evt_inst[X], evt_vol[X] filled with parsed data
;         seq_evt_ptr advanced, seq_evt_row[X] = next event's row
; ==========================================================================
parse_event:
    stx zp_channel
    
    ; --- Setup Pointer ---
    lda seq_evt_ptr_lo,x
    sta trk_ptr
    lda seq_evt_ptr_hi,x
    sta trk_ptr+1
    
    ; --- Read Note Byte (offset 1, skip row byte) ---
    ldy #1
    lda (trk_ptr),y
    sta zp_temp                 ; Save raw note byte (has flags)
    and #$3F                    ; Extract note value (bits 0-5)
    ldx zp_channel
    sta evt_note,x
    iny                         ; Y = 2 (minimum event size)
    
    ; --- Check Instrument Flag (bit 7 of note byte) ---
    lda zp_temp
    bpl @use_last_inst          ; Bit 7 clear = no inst/vol bytes
    
    ; --- Read Instrument Byte ---
    lda (trk_ptr),y
    sta zp_temp                 ; Save raw inst byte (has vol flag)
    and #$7F                    ; Extract instrument (bits 0-6)
    ldx zp_channel
    sta evt_inst,x
    sta seq_last_inst,x         ; Update last used
    iny                         ; Y = 3
    
    ; --- Check Volume Flag (bit 7 of inst byte) ---
    lda zp_temp
    bpl @use_last_vol           ; Bit 7 clear = no vol byte
    
    ; --- Read Volume Byte ---
    lda (trk_ptr),y
    and #$0F                    ; Extract volume (bits 0-3)
    ldx zp_channel
    sta evt_vol,x
    sta seq_last_vol,x          ; Update last used
    iny                         ; Y = 4
    jmp @advance_ptr
    
@use_last_vol:
    ; Inst was present but vol wasn't - use last vol
    ldx zp_channel
    lda seq_last_vol,x
    sta evt_vol,x
    jmp @advance_ptr
    
@use_last_inst:
    ; Neither inst nor vol present - use last values for both
    ldx zp_channel
    lda seq_last_inst,x
    sta evt_inst,x
    lda seq_last_vol,x
    sta evt_vol,x
    ; Y = 2 (only row + note bytes consumed)
    
@advance_ptr:
    ; --- Advance Event Pointer by Y Bytes ---
    ldx zp_channel
    tya
    clc
    adc seq_evt_ptr_lo,x
    sta seq_evt_ptr_lo,x
    bcc @no_carry
    inc seq_evt_ptr_hi,x
@no_carry:

    ; --- Load Next Event's Row Number ---
    lda seq_evt_ptr_lo,x
    sta trk_ptr
    lda seq_evt_ptr_hi,x
    sta trk_ptr+1
    ldy #0
    lda (trk_ptr),y             ; Next row number (or $FF = end)
    sta seq_evt_row,x
    
    rts

; ==========================================================================
; TRIGGER_NOTE - Start Playing Note on Channel
; ==========================================================================
; Triggers a note or note-off on the specified channel.
; Called with IRQ disabled to ensure tight timing between channels.
;
; Input:  X = channel (0-2)
;         evt_note[X] = note (0=off, 1-36)
;         evt_inst[X] = instrument/sample index
; ==========================================================================
trigger_note:
    lda evt_note,x
    beq @note_off               ; Note = 0 means silence
    
    ; --- Prepare Tracker_PlayNote Arguments ---
    ; API: A = sample index (0-127)
    ;      X = note index (0-35)
    ;      Y = channel (0-2)
    
    stx zp_channel              ; Save channel
    
    sec
    sbc #1                      ; Convert note 1-36 to index 0-35
    sta zp_temp                 ; Save note index
    
    ldx zp_channel
    lda evt_inst,x
    and #$7F                    ; A = sample index (clear any stray bit 7)
    
    ldx zp_temp                 ; X = note index
    ldy zp_channel              ; Y = channel
    
    jmp Tracker_PlayNote        ; Tail call optimization

@note_off:
    ; --- Silence Channel ---
    ; Uses indexed jump would be slower than branches for 3 cases
    cpx #0
    bne @not_ch0
    lda #0
    sta trk0_active
    lda #SILENCE
    sta AUDC1
    rts
@not_ch0:
    cpx #1
    bne @ch2
    lda #0
    sta trk1_active
    lda #SILENCE
    sta AUDC2
    rts
@ch2:
    lda #0
    sta trk2_active
    lda #SILENCE
    sta AUDC3
    rts

; ==========================================================================
; SEQ_INIT - Initialize Sequencer State
; ==========================================================================
; Resets all sequencer state to beginning of song.
; Silences all channels and loads first songline.
; ==========================================================================
seq_init:
    ; --- Reset Counters ---
    lda #0
    sta seq_songline
    sta seq_row
    sta seq_tick
    sta seq_playing
    
    ; --- Initialize Per-Channel State ---
    ldx #2
@init_loop:
    lda #0
    sta seq_last_inst,x
    sta evt_trigger,x
    lda #15                     ; Default volume = maximum
    sta seq_last_vol,x
    dex
    bpl @init_loop
    
    ; --- Silence All Channels ---
    lda #0
    sta trk0_active
    sta trk1_active
    sta trk2_active
    lda #SILENCE
    sta AUDC1
    sta AUDC2
    sta AUDC3
    
    ; --- Load First Songline ---
    jsr seq_load_songline
    rts

; ==========================================================================
; SEQ_STOP - Stop Playback and Silence
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
; SEQ_LOAD_SONGLINE - Setup Pattern Pointers for Current Songline
; ==========================================================================
; Reads pattern indices from song data arrays.
; Sets up event pointers for each channel.
; Calculates maximum pattern length.
; Loads first event row for each channel.
; ==========================================================================
seq_load_songline:
    ldx seq_songline
    
    ; --- Load Speed for This Songline ---
    lda SONG_SPEED,x
    sta seq_speed
    
    ; --- Reset Row Counter ---
    lda #0
    sta seq_row
    sta seq_max_len
    
    ; ===== Channel 0 =====
    lda SONG_PTN_CH0,x
    tay                         ; Y = pattern index
    
    ; Track max pattern length
    lda PATTERN_LEN,y
    cmp seq_max_len
    bcc @no_max_0
    sta seq_max_len
@no_max_0:
    
    ; Set event pointer to pattern start
    lda PATTERN_PTR_LO,y
    sta seq_evt_ptr_lo
    lda PATTERN_PTR_HI,y
    sta seq_evt_ptr_hi
    
    ; Load first event's row number
    sta trk_ptr+1
    lda seq_evt_ptr_lo
    sta trk_ptr
    ldy #0
    lda (trk_ptr),y
    sta seq_evt_row
    
    ; ===== Channel 1 =====
    ldx seq_songline
    lda SONG_PTN_CH1,x
    tay
    
    lda PATTERN_LEN,y
    cmp seq_max_len
    bcc @no_max_1
    sta seq_max_len
@no_max_1:
    
    lda PATTERN_PTR_LO,y
    sta seq_evt_ptr_lo+1
    lda PATTERN_PTR_HI,y
    sta seq_evt_ptr_hi+1
    
    sta trk_ptr+1
    lda seq_evt_ptr_lo+1
    sta trk_ptr
    ldy #0
    lda (trk_ptr),y
    sta seq_evt_row+1
    
    ; ===== Channel 2 =====
    ldx seq_songline
    lda SONG_PTN_CH2,x
    tay
    
    lda PATTERN_LEN,y
    cmp seq_max_len
    bcc @no_max_2
    sta seq_max_len
@no_max_2:
    
    lda PATTERN_PTR_LO,y
    sta seq_evt_ptr_lo+2
    lda PATTERN_PTR_HI,y
    sta seq_evt_ptr_hi+2
    
    sta trk_ptr+1
    lda seq_evt_ptr_lo+2
    sta trk_ptr
    ldy #0
    lda (trk_ptr),y
    sta seq_evt_row+2
    
    rts

; ==========================================================================
; UPDATE_DISPLAY - Refresh Status Line
; ==========================================================================
update_display:
    ; --- Songline Position ---
    lda seq_songline
    jsr byte_to_hex
    stx song_pos_display
    sta song_pos_display+1
    
    ; --- Row Position ---
    lda seq_row
    jsr byte_to_hex
    stx row_display
    sta row_display+1
    
    ; --- Current Speed ---
    lda seq_speed
    jsr byte_to_hex
    stx speed_display
    sta speed_display+1
    
    rts

; ==========================================================================
; BYTE_TO_HEX - Convert Byte to Two ASCII Hex Digits
; ==========================================================================
; Input:  A = byte value
; Output: X = high nibble as ASCII hex digit
;         A = low nibble as ASCII hex digit
; ==========================================================================
byte_to_hex:
    sta zp_temp                 ; Save original value
    lsr                         ; Shift high nibble to low
    lsr
    lsr
    lsr
    tax
    lda hex_chars,x             ; Look up ASCII for high nibble
    tax                         ; X = high digit
    lda zp_temp                 ; Restore original
    and #$0F                    ; Mask low nibble
    tay
    lda hex_chars,y             ; Look up ASCII for low nibble
    rts                         ; A = low digit, X = high digit

hex_chars:
    dta d"0123456789ABCDEF"

; ==========================================================================
; INCLUDED MODULES
; ==========================================================================
    icl "tracker/tracker_api.asm"
    icl "tracker/tracker_irq.asm"

; ==========================================================================
; DATA TABLES
; ==========================================================================
    icl "pitch/pitch_tables.asm"
    icl "pitch/LUT_NIBBLES.asm"
    icl "common/pokey_setup.asm"
    
    ; --- Song Data (exported from Music Tracker) ---
    icl "SONG_DATA.asm"
    
    ; --- Sample Data (from PokeyVQ encoder) ---
    icl "SAMPLE_DIR.asm"
    icl "VQ_LO.asm"
    icl "VQ_HI.asm"
    icl "VQ_BLOB.asm"
    icl "VQ_INDICES.asm"

    run start
