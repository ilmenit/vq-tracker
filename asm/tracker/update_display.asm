; ==========================================================================
; UPDATE_DISPLAY.ASM - Display Update (SUBROUTINE)
; ==========================================================================
; Updates the on-screen display with current playback position.
;
; Called once per frame (during VBLANK) to show real-time position.
; When BLANK_SCREEN = 1, this routine is only called from wait_loop
; (idle state), never from main_loop (screen is off during playback).
;
; Display Format:
;   "VQ TRACKER - [SPACE] play/stop [R] reset"
;   "      SONG:XX   ROW:XX   SPD:XX         "
;
; Input:  seq_songline, seq_row, seq_speed
; Output: Display text updated
; Uses:   A, X, byte_to_dec subroutine
; ==========================================================================

update_display:
    ; --- Update songline number ---
    lda seq_songline
    jsr byte_to_dec
    stx song_pos_display        ; Tens digit
    sta song_pos_display+1      ; Ones digit
    
    ; --- Update row number ---
    lda seq_row
    jsr byte_to_dec
    stx row_display
    sta row_display+1
    
    ; --- Update speed ---
    lda seq_speed
    jsr byte_to_dec
    stx speed_display
    sta speed_display+1
    
    rts

; ==========================================================================
; BYTE_TO_DEC - Convert byte to 2-digit ATASCII (SUBROUTINE)
; ==========================================================================
; Converts a value 0-99 to two ATASCII digit characters.
;
; Input:  A = value to convert (0-99)
; Output: X = tens digit (ATASCII '0'-'9')
;         A = ones digit (ATASCII '0'-'9')
; ==========================================================================
byte_to_dec:
    ldx #0                      ; Tens counter
udsp_btd_loop:
    cmp #10
    bcc udsp_btd_done           ; Less than 10? Done
    sec
    sbc #10                     ; Subtract 10
    inx                         ; Increment tens
    bne udsp_btd_loop           ; Always branches (X never 0 here)
udsp_btd_done:
    ; A = ones digit (0-9)
    ; X = tens digit (0-9)
    clc
    adc #$10                    ; Convert to ATASCII
    pha                         ; Save ones digit
    txa
    clc
    adc #$10                    ; Convert tens to ATASCII
    tax                         ; X = tens digit (ATASCII)
    pla                         ; A = ones digit (ATASCII)
    rts
