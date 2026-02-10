; ==========================================================================
; PARSE_EVENT.ASM - Variable-Length Event Parser (SUBROUTINE)
; ==========================================================================
; Parses one event from the pattern data stream for a channel.
; Events use variable-length encoding to minimize memory usage.
;
; Event Format:
; =============
; BYTE 0: row      - Row number (0-254), or $FF = end of pattern
; BYTE 1: note     - Bit 7: inst follows, Bits 0-5: note (0=off, 1-36=note)
; BYTE 2: [inst]   - Optional. Bit 7: vol follows, Bits 0-6: instrument
; BYTE 3: [vol]    - Optional. Bits 0-3: volume (0-15)
;
; Encoding Rules:
; ===============
; - If note & $80 == 0: No instrument/volume (use last values)
; - If note & $80 != 0: Instrument byte follows
;   - If inst & $80 == 0: No volume (use last value)
;   - If inst & $80 != 0: Volume byte follows
;
; Event Sizes:
; ============
; | Scenario         | Bytes | Format                    |
; |------------------|-------|---------------------------|
; | Same inst+vol    | 2     | row, note                 |
; | New inst only    | 3     | row, note|$80, inst       |
; | New inst+vol     | 4     | row, note|$80, inst|$80, vol |
;
; REGISTER CONTRACT:
; ==================
; Input:  X = Channel index (0-3), must be valid
;         seq_evt_ptr[X] = pointer to current event (row byte)
; Output: evt_note[X] = note value (0=off, 1-36=note)
;         evt_inst[X] = instrument index (0-127)
;         evt_vol[X]  = volume (0-15)
;         seq_evt_ptr[X] = advanced to next event
;         seq_evt_row[X] = next event's row number ($FF = end)
; Clobbers: A, X, Y
; Preserves: (nothing - caller must save if needed)
; Uses ZP:  trk_ptr, parse_temp, parse_channel
;
; Y REGISTER TRACKS EVENT SIZE:
;   Y=2 at @pe_use_last (note only, use last inst/vol)
;   Y=3 at @pe_use_last_vol (note+inst, use last vol)
;   Y=4 at full path (note+inst+vol)
; ==========================================================================

parse_event:
    stx parse_channel           ; Save channel index (X may be clobbered)
    
    ; Setup pointer to current event
    ; Entry: X = channel (0-3)
    lda seq_evt_ptr_lo,x
    sta trk_ptr
    lda seq_evt_ptr_hi,x
    sta trk_ptr+1
    ; Now: trk_ptr = address of current event (row byte at offset 0)
    
    ; --- Read note byte (offset 1, row is at offset 0) ---
    ldy #1
    lda (trk_ptr),y             ; A = note byte (bit 7=inst flag, bits 0-5=note)
    sta parse_temp              ; Save full byte for flag check
    and #$3F                    ; Extract note (bits 0-5), A = 0-36
    ldx parse_channel           ; Restore channel index
    sta evt_note,x
    iny                         ; Y = 2 (position after row+note)
    
    ; --- Check if instrument follows (bit 7 of note byte) ---
    lda parse_temp              ; A = original note byte
    bpl @pe_use_last            ; Bit 7 clear = no inst/vol, use last values
    
    ; --- Read instrument byte ---
    ; Y = 2 here
    lda (trk_ptr),y             ; A = inst byte (bit 7=vol flag, bits 0-6=inst)
    sta parse_temp              ; Save for volume flag check
    and #$7F                    ; Extract instrument (bits 0-6), A = 0-127
    ldx parse_channel           ; Restore X (clobbered by any Y-indexed load)
    sta evt_inst,x
    sta seq_last_inst,x         ; Update "last" for future events
    iny                         ; Y = 3 (position after row+note+inst)
    
    ; --- Check if volume follows (bit 7 of inst byte) ---
    lda parse_temp              ; A = original inst byte
    bpl @pe_use_last_vol        ; Bit 7 clear = no vol, use last value
    
    ; --- Read volume byte ---
    ; Y = 3 here
    lda (trk_ptr),y             ; A = vol byte (bits 0-3 = volume)
    and #$0F                    ; Extract volume (bits 0-3), A = 0-15
    ldx parse_channel
    sta evt_vol,x
    sta seq_last_vol,x          ; Update "last" for future events
    iny                         ; Y = 4 (total event size: row+note+inst+vol)
    jmp @pe_advance
    
@pe_use_last_vol:
    ; Volume not specified - use last value
    ; Y = 3 here (row+note+inst consumed)
    ldx parse_channel
    lda seq_last_vol,x
    sta evt_vol,x
    jmp @pe_advance
    
@pe_use_last:
    ; Neither inst nor vol specified - use last values for both
    ; Y = 2 here (only row+note consumed)
    ldx parse_channel
    lda seq_last_inst,x
    sta evt_inst,x
    lda seq_last_vol,x
    sta evt_vol,x
    ; Fall through to @pe_advance with Y = 2

@pe_advance:
    ; --- Advance event pointer by Y bytes ---
    ; Y = 2, 3, or 4 depending on path taken
    ldx parse_channel
    tya                         ; A = bytes consumed (Y value)
    clc
    adc seq_evt_ptr_lo,x
    sta seq_evt_ptr_lo,x
    bcc @pe_no_carry
    inc seq_evt_ptr_hi,x
@pe_no_carry:

    ; --- Read next event's row number ---
    ; seq_evt_ptr now points to NEXT event
    lda seq_evt_ptr_lo,x
    sta trk_ptr
    lda seq_evt_ptr_hi,x
    sta trk_ptr+1
    ldy #0
    lda (trk_ptr),y             ; Row number of next event (or $FF = end)
    sta seq_evt_row,x           ; Store for dispatch check
    
    rts
    ; Exit: A = next row, X = channel, Y = 0
    ; evt_note/inst/vol[X] populated, seq_evt_row[X] = next event row
