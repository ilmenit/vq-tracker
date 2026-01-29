; ==========================================================================
; POKEY Initialization
; ==========================================================================
; Expects: PLAY_RATE, FAST_MODE (optional)
;
; FIXED: Uses $10 for silence instead of $00
;        $00 activates polynomial noise generation
;        $10 = Volume-only mode with volume 0 = true silence
; ==========================================================================

    ; --- Unified Setup using VQ_CFG constants ---
    
Pokey_Setup:
    ; Step 1: Clear IRQEN FIRST (prevent spurious IRQs)
    lda #0
    sta IRQEN

    ; Step 2: Enter Initialization Mode
    sta SKCTL           ; Resets clocks and polynomial counters (A=0)

    ; Step 3: Init Channels to SILENCE
    ; CRITICAL FIX: Use $10 (volume-only mode, volume=0) for true silence
    ; Previously used $00 which causes POKEY to generate polynomial noise!
    lda #$10            ; Bit 4 = Volume-only mode, bits 0-3 = 0 (volume)
    sta AUDC1
    sta AUDC2
    sta AUDC3
    sta AUDC4
    
    ; Set timer frequencies
    lda #AUDF1_VAL
    sta AUDF1
    sta AUDF2
    sta AUDF3
    sta AUDF4
    
    ; Init State
    lda #0
    sta nibble_state
    
    ; Step 4: Set Audio Control Register
    .if AUDCTL_VAL = 0
        sta AUDCTL          ; A is now 0
    .else
        lda #AUDCTL_VAL
        sta AUDCTL
    .endif
    
    ; Step 5: Exit Initialization Mode
    lda #$03            ; Bits 0-1 = 1 (enable keyboard scan + serial)
    sta SKCTL
    
    ; Wait for one scanline (optional but good practice)
    ; (Skipped here for compactness, usually not strictly required if no immediate audio)

    ; Enable IRQs
    lda #IRQ_MASK
    sta IRQEN
    rts
