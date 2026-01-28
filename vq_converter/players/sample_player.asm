; ==========================================================================
; POKEY SAMPLE PLAYER (Refactored)
; --------------------------------------------------------------------------
; Specialized player for VQ-Compressed samples (Fixed Algorithm).
; Supports Multi-Sample playback triggered by Keyboard (A-Z).
; No Pitch Control - Plays samples at original encoded speed.
;
; Use Case: Turn-based games, Soundboards, Simple music.
; ==========================================================================

    icl "common/atari.inc"
    icl "common/zeropage.inc"
    icl "common/macros.inc"
    icl "common/copy_os_ram.asm"

    ; Load Configuration
    icl "VQ_CFG.asm"
    
    ; Enforce MULTI_SAMPLE (Sample Player assumes this structure)
    .ifndef MULTI_SAMPLE
        .error "sample_player.asm requires MULTI_SAMPLE=1 in VQ_CFG.asm"
    .endif
    .ifndef ALGO_FIXED
        .error "sample_player.asm requires ALGO_FIXED=1"
    .endif

    ORG $2000

; --- DISPLAY LIST DATA ---
text_to_print:
    dta d"  [SAMPLE PLAYER]  PRESS A-Z TO PLAY    "

dlist:
    .byte $70,$70,$70           ; 24 blank lines
    .byte $42,<text_to_print,>text_to_print
    .byte $70,$70
    .byte $41,<dlist,>dlist

; --- MAIN ENTRY ---
start:
    sei
    ldx #$FF
    txs
    
    ; Disable IRQ/DMA
    lda #0
    sta NMIEN
    sta IRQEN
    sta DMACTL
    
    ; Enable RAM
    lda #$FE
    sta PORTB
    ; CopyOSRomToRam called via INI segment automatically

    ; Setup Custom Interrupts
    lda #<nmi
    sta $FFFA
    lda #>nmi
    sta $FFFA+1

    lda #<IRQ_Handler
    sta $FFFE
    lda #>IRQ_Handler
    sta $FFFE+1

    ; Setup Display
    lda #<dlist
    sta DLISTL
    lda #>dlist
    sta DLISTH
    lda #34
    sta DMACTL
    lda #$C0
    sta NMIEN
    
    ; Setup Keyboard
    lda #0
    sta SKCTL
    lda #3
    sta SKCTL
    
    ; Reset Player State
    lda #$FF
    sta sample_finished
    sta current_sample
    
    lda #3
    sta SKCTL
    cli

main_loop:
    ; Status Color
    lda sample_finished
    bne show_idle
    
    lda #$40    ; Green (Playing)
    sta COLBK
    jmp check_input
    
show_idle:
    lda #$20    ; Orange (Idle)
    sta COLBK

check_input:
    ; Check if key pressed
    lda SKSTAT
    and #4
    bne main_loop
    
    lda KBCODE
    ldx #25     ; Scan A-Z
search_key:
    cmp key_table,x
    beq found_key
    dex
    bpl search_key
    jmp main_loop

found_key:
    txa         ; A = Sample Index
    
    ; Range Check
    cmp #SAMPLE_COUNT   ; Defined in SAMPLE_DIR.asm
    bcs main_loop
    
    ; Check if already playing same sample
    cmp current_sample
    bne new_sample
    ldy sample_finished
    beq main_loop       ; Ignore re-trigger if running
    
new_sample:
    sta current_sample
    jsr PokeyVQ_Init    ; Init Engine with Sample Index in A
    jmp main_loop

nmi:
    rti

; --- ENGINE: INITIALIZATION ---
PokeyVQ_Init:
    ; Input: A = Sample Index
    tax
    
    ; Load Start/End Pointers from Directory
    lda SAMPLE_START_LO,x
    sta stream_ptr
    lda SAMPLE_START_HI,x
    sta stream_ptr+1
    
    lda SAMPLE_END_LO,x
    sta stream_end
    lda SAMPLE_END_HI,x
    sta stream_end+1
    
    lda #0
    sta sample_finished
    sta sample_len
    
    ; Hardware Setup
    jsr Pokey_Setup ; Implemented in common/pokey_setup.asm
    
    ; Setup Display (ensure DMA on)
    lda #34
    sta DMACTL
    
    ; Enable Timer IRQ
    lda #IRQ_MASK
    sta IRQEN
    lda #0
    sta STIMER
    rts

; --- ENGINE: IRQ HANDLER ---
IRQ_Handler:
    sta irq_save_a
    stx irq_save_x
    sty irq_save_y
    
    ; ACK
    ; ACK (Disable/Enable toggle required)
    lda #0
    sta IRQEN
    lda #IRQ_MASK
    sta IRQEN
    
    ; Check Length
    lda sample_len
    bne play_frame
    
    ; Need New Vector/Sample
    jsr fetch_next ; Implemented in algo_*.asm
    jmp irq_done        ; Fix: fetch_next already plays a sample, so exit immediately
    
    ; Fall through intentionally removed to prevent Double-Play

    
play_frame:
    jsr play_sample ; Implemented in algo_*.asm

irq_done:
    lda irq_save_a
    ldx irq_save_x
    ldy irq_save_y
    rti

; --- TABLES ---
key_table:
    .byte $3F,$15,$12,$3A,$2A,$38,$3D,$39,$0D,$01,$05,$00,$25
    .byte $23,$08,$0A,$2F,$28,$3E,$2D,$0B,$10,$2E,$16,$2B,$17

; --- INCLUDES ---
    ; Algorithm Implementation (fetch_next, play_sample)
    icl "fixed/algo_fixed.asm"
    
    ; Hardware Helpers
    icl "common/pokey_setup.asm"
    
    ; Data
    icl "SAMPLE_DIR.asm"
    icl "VQ_LENS.asm"
    icl "VQ_LO.asm"
    icl "VQ_HI.asm"
    icl "VQ_BLOB.asm"
    icl "VQ_INDICES.asm"

.if CHANNELS == 1
.ifdef USE_FAST_CPU
    icl "LUT_NIBBLES.asm"
.endif
.endif

.ifdef DEBUG_COMPILATION
    .print "End of Data: ", *
.endif

    .if * >= $C000
        .print "Data section too large by ", *-$C000
        .error "Lower Quality or playback Rate"
    .endif

    run start
