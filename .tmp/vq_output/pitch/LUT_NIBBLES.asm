; ==========================================================================
; LUT_NIBBLES.asm - Lookup Tables for Fast Nibble Extraction
; ==========================================================================
; These tables combine nibble extraction with AUDC mask ($10) in one lookup.
; Saves ~5 cycles per sample vs inline shift/mask operations.
;
; Usage:
;   lda (sample_ptr),y    ; Load packed byte
;   tax
;   lda LUT_NIBBLE_LO,x   ; Get low nibble with mask (even samples)
;   ; or
;   lda LUT_NIBBLE_HI,x   ; Get high nibble with mask (odd samples)
;
; Each entry = (nibble_value) | $10 (volume-only mode)
; ==========================================================================

; Low Nibble Table: LUT_NIBBLE_LO[i] = (i & $0F) | $10
LUT_NIBBLE_LO:
LUT_LO:                     ; Alias for pitch_player compatibility
    :256 dta [[#&$0F]|$10]

; High Nibble Table: LUT_NIBBLE_HI[i] = (i >> 4) | $10  
LUT_NIBBLE_HI:
LUT_HI:                     ; Alias for pitch_player compatibility
    :256 dta [[#>>4]|$10]
