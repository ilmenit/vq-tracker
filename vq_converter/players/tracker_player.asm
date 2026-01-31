; ==========================================================================
; POKEY TRACKER PLAYER (POLYPHONIC PITCH - FIXED)
; ==========================================================================
; 3-Channel Polyphonic Player for VQ Samples with Pitch Control.
; Each channel plays independently with its own sample/pitch/position.
;
; Use Case: Interactive Music, Tracker-style playback.
; Requirements: MULTI_SAMPLE=1, PITCH_CONTROL=1, ALGO_FIXED=1 in VQ_CFG.asm
;
; Data Format: Single-channel nibble-packed (8 bytes per 16-sample vector)
; Hardware: Uses AUDC1, AUDC2, AUDC3 for 3 independent channels
;
; FIXES APPLIED:
; - Proper nibble extraction (was reading raw packed bytes)
; - Correct byte offset calculation (vector_offset/2, not vector_offset)
; - Output BEFORE advance (was skipping sample 0)
; - Proper silence value ($10 not $00)
; - AUDC mask application after nibble extraction
; ==========================================================================

    icl "common/atari.inc"
    
    ; Define TRACKER mode for zeropage.inc
    TRACKER = 1
    icl "common/zeropage.inc" 
    
    icl "common/macros.inc"
    icl "common/copy_os_ram.asm"

    ; Load Configuration
    icl "VQ_CFG.asm"
    
    ; Enforce Configuration
    .ifndef MULTI_SAMPLE
        .error "tracker_player.asm requires MULTI_SAMPLE=1"
    .endif
    .ifndef PITCH_CONTROL
        .error "tracker_player.asm requires PITCH_CONTROL=1"
    .endif
    .ifndef ALGO_FIXED
        .error "tracker_player.asm requires ALGO_FIXED=1"
    .endif
    .if MIN_VECTOR != MAX_VECTOR
        .error "tracker_player.asm requires fixed vector size (MIN_VECTOR must equal MAX_VECTOR)"
    .endif
    .if MIN_VECTOR < 2 || MIN_VECTOR > 16
        .error "tracker_player.asm requires vector size between 2 and 16"
    .endif
    .if (MIN_VECTOR & 1) != 0
        .error "tracker_player.asm requires even vector size (2, 4, ... 16)"
    .endif

    ORG $2000

; ==========================================================================
; DISPLAY LIST DATA
; ==========================================================================
text_to_print:
    dta d"Q-P=SMP 1-4=OCT ZXCV=NOTE CH:"
channel_display:
    dta d"1"                ; Shows next channel (1-3)
    dta d"  "
octave_display:
    dta d"1"
note_display:
    dta d"C "
    
status_display:
    dta d"  [POLYPHONIC TRACKER]  "

dlist:
    .byte $70,$70,$70
    .byte $42,<text_to_print,>text_to_print
    .byte $70
    .byte $42,<status_display,>status_display
    .byte $70,$70
    .byte $41,<dlist,>dlist

; ==========================================================================
; VARIABLES (UI specific)
; ==========================================================================
current_octave:   .byte 0
current_semitone: .byte 0
display_sample:   .byte 0 
next_channel:     .byte 0       ; Round-robin allocator (0-2)
last_key:         .byte $FF     ; Last processed key (for edge detection)

; ==========================================================================
; MAIN ENTRY
; ==========================================================================
start:
    sei
    ldx #$FF
    txs
    
    ; Disable System IRQ
    lda #0
    sta NMIEN
    sta IRQEN
    sta DMACTL
    lda #$FE
    sta PORTB
    
    ; Interrupt Vector Setup
    lda #<nmi
    sta $FFFA
    lda #>nmi
    sta $FFFA+1
    
    lda #<Tracker_IRQ
    sta $FFFE
    lda #>Tracker_IRQ
    sta $FFFE+1

    ; Display Setup
    lda #<dlist
    sta DLISTL
    lda #>dlist
    sta DLISTH
    lda #34
    sta DMACTL
    lda #$C0
    sta NMIEN
    
    ; Keyboard Init
    lda #0
    sta SKCTL
    lda #3
    sta SKCTL
    
    ; Init internal state
    lda #0
    sta current_octave
    sta current_semitone
    sta display_sample
    sta next_channel
    
    lda #$FF
    sta last_key            ; No key pressed initially
    
    jsr update_display
    jsr update_channel_display
    
    ; Clear All Channels
    jsr Clear_All_Channels
    
    ; Hardware Setup
    jsr Pokey_Setup
    
    ; Enable Timer IRQ
    lda #IRQ_MASK
    sta IRQEN
    lda #$00
    sta STIMER
    
    cli

; ==========================================================================
; MAIN LOOP
; ==========================================================================
main_loop:
    ; UI Color - Flash if any channel active
    lda trk0_active
    ora trk1_active
    ora trk2_active
    beq show_idle
    lda #$40              ; Green while playing
    sta COLBK
    jmp check_input
show_idle:
    lda #$20              ; Dark when idle
    sta COLBK

check_input:
    ; --- KEYBOARD EDGE DETECTION ---
    ; We want to detect NEW keypresses, not wait for release
    lda SKSTAT
    and #4                  ; Bit 2: 1 = key pressed, 0 = no key
    bne @key_pressed
    
    ; No key currently pressed - reset last_key to allow re-trigger
    lda #$FF
    sta last_key
    jmp main_loop
    
@key_pressed:
    ; A key is pressed - check if it's a NEW key
    lda KBCODE
    cmp last_key
    beq main_loop           ; Same key still held - ignore (already triggered)
    
    ; New key detected! Store it and process
    sta last_key
    
    ; --- PIANO LOGIC ---
    ; 1. Check Samples (Q-P keys)
    ldx #9
search_sample:
    cmp sample_key_table,x
    beq found_sample
    dex
    bpl search_sample
    
    ; 2. Check Octaves (1-4 keys)
    ldx #3
search_octave:
    cmp octave_key_table,x
    beq found_octave
    dex
    bpl search_octave
    
    ; 3. Check White Keys (ZXCVBNM)
    ldx #6
search_white:
    cmp white_key_table,x
    beq found_white
    dex
    bpl search_white
    
    ; 4. Check Black Keys (SDFGH)
    ldx #4
search_black:
    cmp black_key_table,x
    beq found_black
    dex
    bpl search_black
    
    jmp main_loop

found_sample:
    stx display_sample
    jmp main_loop

found_octave:
    stx current_octave
    jsr update_display
    jmp main_loop

found_white:
    lda white_semitones,x
    sta current_semitone
    jsr update_display
    jmp play_trigger

found_black:
    lda black_semitones,x
    sta current_semitone
    jsr update_display
    jmp play_trigger

play_trigger:
    ; Calculate Note Index
    ldx current_octave
    lda octave_base,x
    clc
    adc current_semitone
    tax                     ; X = Note (0-47)
    
    ; Play on next channel (round-robin)
    ldy next_channel
    lda display_sample      ; A = Sample index
    
    ; CRITICAL: Disable IRQ during setup to prevent race conditions
    sei
    jsr Tracker_PlayNote
    cli
    
    ; Advance to next channel
    inc next_channel
    lda next_channel
    cmp #3
    bne @skip_wrap
    lda #0
    sta next_channel
@skip_wrap:
    
    ; Update channel display
    jsr update_channel_display
    
    jmp main_loop

nmi:
    rti

update_display:
    lda current_octave
    clc
    adc #$11                ; Convert to ATASCII digit
    sta octave_display
    ldx current_semitone
    lda note_names,x
    sta note_display
    rts

update_channel_display:
    ; Display next channel as 1, 2, or 3 (not 0, 1, 2)
    lda next_channel
    clc
    adc #$11                ; Convert 0->1, 1->2, 2->3 in ATASCII
    sta channel_display
    rts

Clear_All_Channels:
    lda #0
    sta trk0_active
    sta trk1_active
    sta trk2_active
    ; Set POKEY to silence (volume-only mode, volume=0)
    lda #$10
    sta AUDC1
    sta AUDC2
    sta AUDC3
    rts

; ==========================================================================
; MODULES
; ==========================================================================
    icl "tracker/tracker_api.asm"
    icl "tracker/tracker_irq.asm"

; ==========================================================================
; LOOKUP TABLES
; ==========================================================================
octave_base:      .byte 0, 12, 24, 36
octave_key_table: .byte $1F, $1E, $1A, $18     ; Keys 1-4
sample_key_table: .byte $2F, $2E, $2A, $28, $2D, $2B, $0B, $0D, $08, $0A ; Q-P
white_key_table:  .byte $17, $16, $12, $10, $15, $23, $25  ; ZXCVBNM
white_semitones:  .byte 0, 2, 4, 5, 7, 9, 11   ; C D E F G A B
black_key_table:  .byte $3E, $3A, $3D, $39, $01 ; SDFGH
black_semitones:  .byte 1, 3, 6, 8, 10         ; C# D# F# G# A#
note_names:       .byte $03, $43, $04, $44, $05, $06, $46, $07, $47, $01, $41, $02

; ==========================================================================
; INCLUDES
; ==========================================================================
    ; Pitch Tables
    icl "pitch/pitch_tables.asm"
    
    ; Nibble Extraction LUTs (Only needed for Packed Mode)
    .ifndef USE_FAST_CPU
        icl "pitch/LUT_NIBBLES.asm"
    .endif
    
    ; POKEY Setup
    icl "common/pokey_setup.asm"
    
    ; Sample Directory
    icl "SAMPLE_DIR.asm"

    ; VQ Codebook Data
    icl "VQ_LO.asm"
    icl "VQ_HI.asm"
    icl "VQ_BLOB.asm"
    icl "VQ_INDICES.asm"

    run start
