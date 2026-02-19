; =============================================================================
; Copy OS ROM to RAM + Relocate charset to $FC00
; =============================================================================
; Phase 1: Copies the OS ROM ($C000-$CFFF and $D800-$FFFF) to the underlying
;          RAM.  This allows the OS ROM to be disabled later while keeping
;          essential data (charset, vectors) in RAM.
;
; Phase 2: Copies the Atari charset from RAM $E000-$E3FF to RAM $FC00-$FFFF.
;          This frees $D800-$FBFF for song data in banking mode.
;          ANTIC uses CHBASE=$FC to read the relocated charset.
;          Screen code 127 (TAB glyph, never displayed) partially overlaps
;          the NMI/IRQ/RESET vectors at $FFFA-$FFFF — patched by start:.
;
; IMPORTANT: This MUST run via INI before the main program!
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
    
    ; =========================================================================
    ; Relocate charset: RAM $E000-$E3FF → RAM $FC00-$FFFF
    ; =========================================================================
    ; In banking mode, $E000 is overwritten by song data (region B).
    ; ANTIC will be set to CHBASE=$FC to read charset from $FC00.
    ; Both source and destination are under OS ROM — need ROM off.
    ; NMI+IRQ are still disabled (safe: $FFFA vectors are temporarily
    ; overwritten in RAM, but NMI can't fire with NMIEN=0).
    lda $D301
    and #$FE                ; ROM off → RAM visible
    sta $D301

    ldy #0
@charset_copy:
    lda $E000,y
    sta $FC00,y
    lda $E100,y
    sta $FD00,y
    lda $E200,y
    sta $FE00,y
    lda $E300,y
    sta $FF00,y
    iny
    bne @charset_copy

    lda $D301
    ora #$01                ; ROM back on (for OS loader)
    sta $D301

    ; Done copying - restore interrupts for OS loader
    ; ROM stays enabled (PORTB bit 0 = 1) which is correct for OS
    lda #$40                ; Enable VBI (bit 6) - OS needs this for loader
    sta $D40E               ; Restore NMIEN
    cli                     ; Re-enable IRQ (needed for SIO disk loading)
    rts

    ini CopyOSRomToRam
