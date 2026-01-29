; ==========================================================================
; TEST_SONG_DATA.asm - Test Pattern for Song Player
; ==========================================================================
; A simple C major scale for testing the song player.
; Plays notes from C-1 up to C-2 and back down.
;
; NOTE ENCODING REFERENCE:
;   GUI C-1 (note 1) → export as 1 → ASM: 1-1=0 → pitch index 0 (1.0x)
;   GUI C-2 (note 13) → export as 13 → ASM: 13-1=12 → pitch index 12 (2.0x)
;   GUI C-3 (note 25) → export as 25 → ASM: 25-1=24 → pitch index 24 (4.0x)
;
; To use: Copy this to SONG_DATA.asm in build directory
; ==========================================================================

SONG_LENGTH = 1

; --- Songline Data ---
SONG_SPEED:
    .byte 6                     ; Speed 6 (8.33 rows/sec at PAL)

SONG_PTN_CH0:
    .byte 0                     ; Pattern 0 on channel 0

SONG_PTN_CH1:
    .byte 1                     ; Pattern 1 on channel 1 (empty)

SONG_PTN_CH2:
    .byte 1                     ; Pattern 1 on channel 2 (empty)

; --- Pattern Directory ---
PATTERN_COUNT = 2

PATTERN_LEN:
    .byte 64                    ; Pattern 0: 64 rows
    .byte 64                    ; Pattern 1: 64 rows (empty)

PATTERN_PTR_LO:
    .byte <PTN_0
    .byte <PTN_1

PATTERN_PTR_HI:
    .byte >PTN_0
    .byte >PTN_1

; --- Pattern Data ---

; Pattern 0: C major scale (C-1 to C-2 and back)
; All notes play at 1.0x-2.0x pitch (base octave)
PTN_0:
    ; Row 0: C-1 (note 1), inst 0, vol 15 - FULL EVENT (first note)
    .byte $00, $81, $80, $0F    ; row=0, note=1|$80, inst=0|$80, vol=15
    ; Row 4: D-1 (note 3) - SAME inst/vol
    .byte $04, $03              ; row=4, note=3
    ; Row 8: E-1 (note 5)
    .byte $08, $05
    ; Row 12: F-1 (note 6)
    .byte $0C, $06
    ; Row 16: G-1 (note 8)
    .byte $10, $08
    ; Row 20: A-1 (note 10)
    .byte $14, $0A
    ; Row 24: B-1 (note 12)
    .byte $18, $0C
    ; Row 28: C-2 (note 13) - One octave up, 2.0x pitch
    .byte $1C, $0D
    ; Row 32: C-2 again
    .byte $20, $0D
    ; Row 36: B-1 (note 12) - Going back down
    .byte $24, $0C
    ; Row 40: A-1 (note 10)
    .byte $28, $0A
    ; Row 44: G-1 (note 8)
    .byte $2C, $08
    ; Row 48: F-1 (note 6)
    .byte $30, $06
    ; Row 52: E-1 (note 5)
    .byte $34, $05
    ; Row 56: D-1 (note 3)
    .byte $38, $03
    ; Row 60: C-1 (note 1) - Back to start
    .byte $3C, $01
    ; End marker
    .byte $FF

; Pattern 1: Empty (silence)
PTN_1:
    .byte $FF

; === END OF TEST SONG DATA ===
