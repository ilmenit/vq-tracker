; =============================================================================
; Copy OS ROM to RAM
; =============================================================================
; Copies the OS ROM ($C000-$CFFF and $D800-$FFFF) to the underlying RAM.
; This allows the OS to be disabled (for more RAM/timing control) while keeping
; the character set and other OS data available in RAM.
;
; IMPORTANT: This MUST run via INI before the main program!
; Without this, disabling ROM also disables the font, breaking display.
; =============================================================================

    ; Temporary ZP pointer for the copy operation
    ; Uses $CB which doesn't conflict with player variables ($80-$BF)
    os_copy_ptr = $CB 

    org $2000   ; OK to use $2000, INI runs this first then main program loads over it

CopyOSRomToRam:
    sei                     ; Disable IRQ
    lda #0 
    sta $D40E               ; Disable NMI (NMIEN)
    
    ; Initialize pointer to start of OS ROM ($C000)
    ldy #$00
    sty os_copy_ptr
    lda #$C0
    sta os_copy_ptr+1
    
    ; Ensure OS ROM is enabled initially (Set Bit 0 of PORTB)
    lda $D301               ; PORTB
    ora #$01
    sta $D301

@copy_loop:
    ; Read from ROM
    lda (os_copy_ptr),y
    
    ; Switch to RAM (Clear Bit 0 of PORTB)
    dec $D301               ; Faster than LDA/AND/STA
    
    ; Write to RAM
    sta (os_copy_ptr),y
    
    ; Switch back to ROM (Set Bit 0 of PORTB)
    inc $D301
    
    iny
    bne @copy_loop
    
    ; Move to next page
    inc os_copy_ptr+1
    
    ; Check if we reached I/O area ($D000-$D7FF)
    lda os_copy_ptr+1
    cmp #$D0
    bne @check_end
    
    ; Skip IO area, jump to $D800 (Charset/FP ROM)
    lda #$D8
    sta os_copy_ptr+1

@check_end:
    ; Check if we wrapped past $FFFF (high byte becomes $00)
    lda os_copy_ptr+1
    bne @copy_loop
    
    ; Done copying - leave RAM enabled (PORTB Bit 0 = 0)
    rts

    ini CopyOSRomToRam
