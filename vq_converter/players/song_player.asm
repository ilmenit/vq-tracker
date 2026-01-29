; ==========================================================================
; SONG PLAYER - Atari 6502 Tracker (Fixed Version v2)
; ==========================================================================
;
; Plays songs exported from the Music Tracker application.
; 3-channel polyphonic playback with per-songline speed control.
;
; FIXES:
;   - Unique local labels (no conflict with tracker_irq.asm)
;   - All long branches use JMP patterns
;   - Modular structure to reduce code size
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
; SEQUENCER STATE
; ==========================================================================
seq_songline:     .byte 0       ; Current songline index
seq_row:          .byte 0       ; Current row within patterns
seq_tick:         .byte 0       ; Tick counter (0 to speed-1)
seq_speed:        .byte 6       ; Current speed (VBLANKs per row)
seq_max_len:      .byte 64      ; Max pattern length for current songline
seq_playing:      .byte 0       ; $FF=playing, $00=stopped

; --- Per-Channel Event Pointers ---
seq_evt_ptr_lo:   .byte 0,0,0
seq_evt_ptr_hi:   .byte 0,0,0
seq_evt_row:      .byte $FF,$FF,$FF

; --- Per-Channel Last Values ---
seq_last_inst:    .byte 0,0,0
seq_last_vol:     .byte 15,15,15

; --- Parsed Event Data ---
evt_note:         .byte 0,0,0
evt_inst:         .byte 0,0,0
evt_vol:          .byte 0,0,0
evt_trigger:      .byte 0,0,0

; --- Temporaries ---
nmi_save_a:       .byte 0
nmi_save_x:       .byte 0
nmi_save_y:       .byte 0
parse_temp:       .byte 0
parse_channel:    .byte 0
last_key_state:   .byte 0       ; For edge detection: 0=released, 4=pressed

; NOTE: seq_ptr is defined in zeropage.inc at $BC (separate from IRQ's trk_ptr)

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
    .byte $70,$70,$70
    .byte $42,<text_line1,>text_line1
    .byte $70
    .byte $42,<text_line2,>text_line2
    .byte $70
    .byte $42,<text_line3,>text_line3
    .byte $70,$70
    .byte $41,<dlist,>dlist

; ==========================================================================
; MAIN ENTRY POINT
; ==========================================================================
start:
    sei
    ldx #$FF
    txs
    
    lda #0
    sta NMIEN
    sta IRQEN
    sta DMACTL
    lda #$FE
    sta PORTB
    
    lda #<nmi_handler
    sta $FFFA
    lda #>nmi_handler
    sta $FFFA+1
    
    lda #<Tracker_IRQ
    sta $FFFE
    lda #>Tracker_IRQ
    sta $FFFE+1

    lda #<dlist
    sta DLISTL
    lda #>dlist
    sta DLISTH
    lda #34
    sta DMACTL
    lda #$C0
    sta NMIEN
    
    lda #0
    sta SKCTL
    lda #3
    sta SKCTL
    
    jsr seq_init
    jsr Pokey_Setup
    
    lda #IRQ_MASK
    sta IRQEN
    lda #$00
    sta STIMER
    
    cli

; ==========================================================================
; MAIN LOOP
; ==========================================================================
main_loop:
    lda seq_playing
    beq ml_idle_color
    lda #$40
    jmp ml_set_color
ml_idle_color:
    lda #$20
ml_set_color:
    sta COLBK
    
    ; --- Edge Detection Keyboard Handling ---
    ; Only trigger on key DOWN edge (not held, not release)
    lda SKSTAT
    and #4                      ; Bit 2: 0=no key, 4=key pressed
    cmp last_key_state          ; Compare with previous state
    beq main_loop               ; Same state = no change, continue
    sta last_key_state          ; Store new state
    
    ; State changed - check direction
    cmp #0
    beq main_loop               ; Went to 0 = key released, ignore
    
    ; Key just pressed (edge: 0 -> 4)
    lda KBCODE
    and #$3F
    
    cmp #$21                    ; SPACE
    bne ml_check_r
    ; Toggle play/stop
    lda seq_playing
    bne ml_do_stop
    lda #$FF
    sta seq_playing
    jmp main_loop
ml_do_stop:
    jsr seq_stop
    jmp main_loop
    
ml_check_r:
    cmp #$28                    ; R
    bne main_loop
    jsr seq_init
    jmp main_loop

; ==========================================================================
; NMI HANDLER - Compact version
; ==========================================================================
nmi_handler:
    sta nmi_save_a
    stx nmi_save_x
    sty nmi_save_y
    
    lda seq_playing
    beq nmi_exit
    
    inc seq_tick
    lda seq_tick
    cmp seq_speed
    bcc nmi_exit
    
    ; Process row
    lda #0
    sta seq_tick
    jsr process_row
    
nmi_exit:
    jsr update_display
    lda nmi_save_a
    ldx nmi_save_x
    ldy nmi_save_y
    rti

; ==========================================================================
; PROCESS_ROW - Called from NMI when tick reaches speed
; ==========================================================================
process_row:
    ; Clear trigger flags
    lda #0
    sta evt_trigger
    sta evt_trigger+1
    sta evt_trigger+2
    
    ; Parse channel 0
    lda seq_evt_row
    cmp seq_row
    bne pr_no_ch0
    ldx #0
    jsr parse_event
    lda #$FF
    sta evt_trigger
pr_no_ch0:

    ; Parse channel 1
    lda seq_evt_row+1
    cmp seq_row
    bne pr_no_ch1
    ldx #1
    jsr parse_event
    lda #$FF
    sta evt_trigger+1
pr_no_ch1:

    ; Parse channel 2
    lda seq_evt_row+2
    cmp seq_row
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
    
    ; Advance row
    inc seq_row
    lda seq_row
    cmp seq_max_len
    bcc pr_done
    
    ; End of pattern
    lda #0
    sta seq_row
    
    inc seq_songline
    lda seq_songline
    cmp #SONG_LENGTH
    bcc pr_next_songline
    
    ; Loop song
    lda #0
    sta seq_songline

pr_next_songline:
    jsr seq_load_songline
    
pr_done:
    rts

; ==========================================================================
; PARSE_EVENT - Decode variable-length event
; Input: X = channel (0-2)
; ==========================================================================
parse_event:
    stx parse_channel
    
    lda seq_evt_ptr_lo,x
    sta seq_ptr
    lda seq_evt_ptr_hi,x
    sta seq_ptr+1
    
    ; Read note byte (skip row at offset 0)
    ldy #1
    lda (seq_ptr),y
    sta parse_temp
    and #$3F
    ldx parse_channel
    sta evt_note,x
    iny
    
    ; Check inst flag
    lda parse_temp
    bpl pe_use_last
    
    ; Read instrument
    lda (seq_ptr),y
    sta parse_temp
    and #$7F
    ldx parse_channel
    sta evt_inst,x
    sta seq_last_inst,x
    iny
    
    ; Check vol flag
    lda parse_temp
    bpl pe_use_last_vol
    
    ; Read volume
    lda (seq_ptr),y
    and #$0F
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
    ldx parse_channel
    tya
    clc
    adc seq_evt_ptr_lo,x
    sta seq_evt_ptr_lo,x
    bcc pe_no_carry
    inc seq_evt_ptr_hi,x
pe_no_carry:

    ; Load next event's row
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
; Input: X = channel (0-2)
; ==========================================================================
trigger_note:
    lda evt_note,x
    beq tn_note_off
    
    stx parse_channel
    
    ; Convert note 1-36 to index 0-35
    sec
    sbc #1
    sta parse_temp
    
    ldx parse_channel
    lda evt_inst,x
    and #$7F
    
    ldx parse_temp              ; X = note index
    ldy parse_channel           ; Y = channel
    jmp Tracker_PlayNote

tn_note_off:
    cpx #0
    bne tn_not_ch0
    lda #0
    sta trk0_active
    lda #SILENCE
    sta AUDC1
    rts
tn_not_ch0:
    cpx #1
    bne tn_ch2
    lda #0
    sta trk1_active
    lda #SILENCE
    sta AUDC2
    rts
tn_ch2:
    lda #0
    sta trk2_active
    lda #SILENCE
    sta AUDC3
    rts

; ==========================================================================
; SEQ_INIT
; ==========================================================================
seq_init:
    lda #0
    sta seq_songline
    sta seq_row
    sta seq_tick
    sta seq_playing
    sta last_key_state          ; Reset keyboard edge detection
    
    ldx #2
si_loop:
    lda #0
    sta seq_last_inst,x
    sta evt_trigger,x
    lda #$FF
    sta seq_evt_row,x
    lda #15
    sta seq_last_vol,x
    dex
    bpl si_loop
    
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
; SEQ_STOP
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
; SEQ_LOAD_SONGLINE
; ==========================================================================
seq_load_songline:
    ldx seq_songline
    
    lda SONG_SPEED,x
    sta seq_speed
    
    lda #0
    sta seq_row
    sta seq_max_len
    
    ; Channel 0
    lda SONG_PTN_CH0,x
    tay
    lda PATTERN_LEN,y
    cmp seq_max_len
    bcc sls_no_max0
    sta seq_max_len
sls_no_max0:
    lda PATTERN_PTR_LO,y
    sta seq_evt_ptr_lo
    lda PATTERN_PTR_HI,y
    sta seq_evt_ptr_hi
    sta seq_ptr+1
    lda seq_evt_ptr_lo
    sta seq_ptr
    ldy #0
    lda (seq_ptr),y
    sta seq_evt_row
    
    ; Channel 1
    ldx seq_songline
    lda SONG_PTN_CH1,x
    tay
    lda PATTERN_LEN,y
    cmp seq_max_len
    bcc sls_no_max1
    sta seq_max_len
sls_no_max1:
    lda PATTERN_PTR_LO,y
    sta seq_evt_ptr_lo+1
    lda PATTERN_PTR_HI,y
    sta seq_evt_ptr_hi+1
    sta seq_ptr+1
    lda seq_evt_ptr_lo+1
    sta seq_ptr
    ldy #0
    lda (seq_ptr),y
    sta seq_evt_row+1
    
    ; Channel 2
    ldx seq_songline
    lda SONG_PTN_CH2,x
    tay
    lda PATTERN_LEN,y
    cmp seq_max_len
    bcc sls_no_max2
    sta seq_max_len
sls_no_max2:
    lda PATTERN_PTR_LO,y
    sta seq_evt_ptr_lo+2
    lda PATTERN_PTR_HI,y
    sta seq_evt_ptr_hi+2
    sta seq_ptr+1
    lda seq_evt_ptr_lo+2
    sta seq_ptr
    ldy #0
    lda (seq_ptr),y
    sta seq_evt_row+2
    
    rts

; ==========================================================================
; UPDATE_DISPLAY
; ==========================================================================
update_display:
    lda seq_songline
    jsr byte_to_hex
    stx song_pos_display
    sta song_pos_display+1
    
    lda seq_row
    jsr byte_to_hex
    stx row_display
    sta row_display+1
    
    lda seq_speed
    jsr byte_to_hex
    stx speed_display
    sta speed_display+1
    rts

byte_to_hex:
    sta parse_temp
    lsr
    lsr
    lsr
    lsr
    tax
    lda hex_chars,x
    tax
    lda parse_temp
    and #$0F
    tay
    lda hex_chars,y
    rts

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
    
    icl "SONG_DATA.asm"
    
    icl "SAMPLE_DIR.asm"
    icl "VQ_LO.asm"
    icl "VQ_HI.asm"
    icl "VQ_BLOB.asm"
    icl "VQ_INDICES.asm"

    run start
