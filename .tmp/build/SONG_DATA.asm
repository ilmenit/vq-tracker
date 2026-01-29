; ==========================================================================
; SONG_DATA.asm - Exported from Atari Sample Tracker
; ==========================================================================
; Title:  Untitled
; Author: 
; ==========================================================================

VOLUME_CONTROL = 0  ; 1=enable volume scaling, 0=disable

SONG_LENGTH = 1

; --- Songline Data ---
SONG_SPEED:
    .byte 6

SONG_PTN_CH0:
    .byte 0
SONG_PTN_CH1:
    .byte 1
SONG_PTN_CH2:
    .byte 2

; --- Pattern Directory ---
PATTERN_COUNT = 3

PATTERN_LEN:
    .byte 64,32,64

PATTERN_PTR_LO:
    .byte <PTN_0,<PTN_1,<PTN_2

PATTERN_PTR_HI:
    .byte >PTN_0,>PTN_1,>PTN_2

; --- Pattern Event Data ---

PTN_0:
    .byte $00,$81,$80,$0F,$04,$03,$08,$05,$0C,$01,$0E,$03,$10,$05,$12,$01
    .byte $14,$03,$16,$05,$18,$03,$1A,$05,$1C,$06,$1E,$05,$20,$06,$22,$08
    .byte $24,$01,$26,$03,$28,$05,$2A,$01,$2C,$03,$2E,$05,$30,$06,$32,$08
    .byte $34,$0A,$36,$06,$38,$08,$3A,$0A,$FF

PTN_1:
    .byte $00,$81,$82,$0F,$02,$03,$04,$01,$06,$03,$08,$01,$0A,$03,$0C,$01
    .byte $0E,$03,$10,$05,$12,$06,$14,$05,$16,$06,$18,$05,$1A,$06,$1C,$05
    .byte $1E,$06,$FF

PTN_2:
    .byte $00,$99,$92,$0F,$02,$19,$04,$18,$06,$18,$08,$19,$0E,$19,$10,$19
    .byte $12,$18,$14,$18,$16,$19,$1C,$16,$1E,$16,$20,$14,$22,$14,$24,$16
    .byte $2A,$16,$2C,$16,$2E,$14,$30,$14,$32,$16,$FF

; === END OF SONG DATA ===