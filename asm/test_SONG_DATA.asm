; Test SONG_DATA.asm with volume control enabled
VOLUME_CONTROL = 1
SONG_LENGTH = 1
SONG_SPEED: .byte $06
SONG_PTN_CH0: .byte $00
SONG_PTN_CH1: .byte $01
SONG_PTN_CH2: .byte $02
PATTERN_COUNT = 3
PATTERN_LEN: .byte $10,$10,$10
PATTERN_PTR_LO: .byte <PTN_00,<PTN_01,<PTN_02
PATTERN_PTR_HI: .byte >PTN_00,>PTN_01,>PTN_02
PTN_00: .byte $00,$C0,$81,$00,$FF
PTN_01: .byte $00,$C0,$81,$00,$FF
PTN_02: .byte $00,$C0,$81,$00,$FF
