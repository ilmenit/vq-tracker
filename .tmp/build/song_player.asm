; ==========================================================================
; SONG PLAYER - Atari 6502 Sample Tracker
; ==========================================================================
; Version: 3.0
;
; Plays songs exported from the Music Tracker GUI application.
; Features:
;   - 3-channel polyphonic playback via VQ-compressed samples
;   - Per-songline speed control
;   - Variable-length event encoding for compact pattern storage
;   - Keyboard control (Space=play/stop, R=restart)
;
; Memory Map:
;   $2000+: Player code and data
;   $80-$BF: Zero page variables (see zeropage.inc)
;
; Hardware:
;   POKEY channels 1-3 for audio output
;   Timer IRQ for sample playback at ~15.7kHz
;   VBI (NMI) for sequencer timing at 50Hz (PAL)
;
; ==========================================================================

    icl "common/atari.inc"
    
    ; Enable tracker mode for zero page layout
    TRACKER = 1
    icl "common/zeropage.inc" 
    icl "common/macros.inc"
    icl "common/copy_os_ram.asm"
    icl "VQ_CFG.asm"
    
    ; Include SONG_DATA early - it defines VOLUME_CONTROL flag
    icl "SONG_DATA.asm"
    
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

; Per-channel last values (for delta encoding)
seq_last_inst:    .byte 0,0,0   ; Last instrument per channel
seq_last_vol:     .byte 15,15,15 ; Last volume per channel

; Parsed event data (current row)
evt_note:         .byte 0,0,0   ; Note for each channel (0=none)
evt_inst:         .byte 0,0,0   ; Instrument for each channel
evt_vol:          .byte 0,0,0   ; Volume for each channel
evt_trigger:      .byte 0,0,0   ; Trigger flag ($FF=trigger note)

; ==========================================================================
; DISPLAY LIST (simple 2-line text display)
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
    dta d"        "

dlist:
    .byte $70,$70,$70           ; 3 blank lines
    .byte $42,<text_line1,>text_line1
    .byte $02                   ; Mode 2 text
    .byte $70
    .byte $42,<text_line2,>text_line2
    .byte $41,<dlist,>dlist     ; Jump back

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
    lda #<nmi_handler
    sta $FFFA
    lda #>nmi_handler
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
    lda #34                     ; Enable DMA
    sta DMACTL
    lda #$C0                    ; Enable NMI
    sta NMIEN
    
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
; MAIN LOOP - Keyboard handling and status display
; ==========================================================================
main_loop:
    ; Visual feedback: green=playing, dark=stopped
    lda seq_playing
    beq ml_idle_color
    lda #$40                    ; Green
    jmp ml_set_color
ml_idle_color:
    lda #$20                    ; Dark gray
ml_set_color:
    sta COLBK
    
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
; NMI HANDLER (VBI) - Sequencer timing at 50Hz
; ==========================================================================
nmi_handler:
    pha
    txa
    pha
    tya
    pha
    
    ; Only process if playing
    lda seq_playing
    beq nmi_exit
    
    ; Tick counter
    inc seq_tick
    lda seq_tick
    cmp seq_speed
    bcc nmi_exit
    
    ; Time for next row
    lda #0
    sta seq_tick
    jsr process_row
    
nmi_exit:
    jsr update_display
    pla
    tay
    pla
    tax
    pla
    rti

; ==========================================================================
; PROCESS_ROW - Parse events and trigger notes
; ==========================================================================
process_row:
    ; Clear trigger flags
    lda #0
    sta evt_trigger
    sta evt_trigger+1
    sta evt_trigger+2
    
    ; Parse each channel if event matches current row
    lda seq_evt_row
    cmp seq_row
    bne pr_no_ch0
    ldx #0
    jsr parse_event
    lda #$FF
    sta evt_trigger
pr_no_ch0:

    lda seq_evt_row+1
    cmp seq_row
    bne pr_no_ch1
    ldx #1
    jsr parse_event
    lda #$FF
    sta evt_trigger+1
pr_no_ch1:

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
    
    ; End of pattern - advance songline
    lda #0
    sta seq_row
    
    inc seq_songline
    lda seq_songline
    cmp SONG_LENGTH
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
    lda #$FF
    sta seq_evt_row,x
    lda #15
    sta seq_last_vol,x
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
seq_load_songline:
    ldx seq_songline
    
    ; Get speed for this songline
    lda SONG_SPEED,x
    sta seq_speed
    
    ; Reset row position
    lda #0
    sta seq_row
    sta seq_max_len
    
    ; === Channel 0 ===
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
    
    ; === Channel 1 ===
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
    
    ; === Channel 2 ===
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
update_display:
    ; Update songline display
    lda seq_songline
    jsr byte_to_dec
    sta song_pos_display
    stx song_pos_display+1
    
    ; Update row display
    lda seq_row
    jsr byte_to_dec
    sta row_display
    stx row_display+1
    
    ; Update speed display
    lda seq_speed
    jsr byte_to_dec
    sta speed_display
    stx speed_display+1
    rts

; Convert A to 2-digit decimal in A (tens), X (ones)
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
    clc
    adc #$10                    ; Convert to ATASCII
    pha
    txa
    clc
    adc #$10
    tax
    pla
    ; Swap: X=tens, A=ones
    pha
    txa
    tax
    pla
    rts

; ==========================================================================
; INCLUDE MODULES
; ==========================================================================
    icl "tracker/tracker_api.asm"
    icl "tracker/tracker_irq.asm"

; ==========================================================================
; INCLUDE DATA
; ==========================================================================
    icl "pitch/pitch_tables.asm"
    icl "pitch/LUT_NIBBLES.asm"
    icl "pitch/VOLUME_SCALE.asm"
    icl "common/pokey_setup.asm"

    ; SONG_DATA.asm included at top (defines VOLUME_CONTROL flag)

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
