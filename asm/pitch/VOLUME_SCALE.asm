; ==========================================================================
; VOLUME_SCALE.asm - Volume Scaling Lookup Table
; ==========================================================================
; Pre-calculated volume scaling for sample playback.
;
; Index format: sample (0-15) + volume_shifted (0, 16, 32, ... 240)
; Result: scaled_sample | $10 (volume-only mode flag)
;
; Formula: VOLUME_SCALE[s + v*16] = round(s * v / 15) | $10
;
; This table is 256 bytes and only included when VOLUME_CONTROL=1
; ==========================================================================

.if VOLUME_CONTROL = 1

VOLUME_SCALE:
    ; Volume  0 (v=0): samples scaled to 0-0
    .byte $10,$10,$10,$10,$10,$10,$10,$10,$10,$10,$10,$10,$10,$10,$10,$10

    ; Volume  1 (v=1): samples scaled to 0-1
    .byte $10,$10,$10,$10,$10,$10,$10,$10,$11,$11,$11,$11,$11,$11,$11,$11

    ; Volume  2 (v=2): samples scaled to 0-2
    .byte $10,$10,$10,$10,$11,$11,$11,$11,$11,$11,$11,$11,$12,$12,$12,$12

    ; Volume  3 (v=3): samples scaled to 0-3
    .byte $10,$10,$10,$11,$11,$11,$11,$11,$12,$12,$12,$12,$12,$13,$13,$13

    ; Volume  4 (v=4): samples scaled to 0-4
    .byte $10,$10,$11,$11,$11,$11,$12,$12,$12,$12,$13,$13,$13,$13,$14,$14

    ; Volume  5 (v=5): samples scaled to 0-5
    .byte $10,$10,$11,$11,$11,$12,$12,$12,$13,$13,$13,$14,$14,$14,$15,$15

    ; Volume  6 (v=6): samples scaled to 0-6
    .byte $10,$10,$11,$11,$12,$12,$12,$13,$13,$14,$14,$14,$15,$15,$16,$16

    ; Volume  7 (v=7): samples scaled to 0-7
    .byte $10,$10,$11,$11,$12,$12,$13,$13,$14,$14,$15,$15,$16,$16,$17,$17

    ; Volume  8 (v=8): samples scaled to 0-8
    .byte $10,$11,$11,$12,$12,$13,$13,$14,$14,$15,$15,$16,$16,$17,$17,$18

    ; Volume  9 (v=9): samples scaled to 0-9
    .byte $10,$11,$11,$12,$12,$13,$14,$14,$15,$15,$16,$17,$17,$18,$18,$19

    ; Volume 10 (v=10): samples scaled to 0-10
    .byte $10,$11,$11,$12,$13,$13,$14,$15,$15,$16,$17,$17,$18,$19,$19,$1A

    ; Volume 11 (v=11): samples scaled to 0-11
    .byte $10,$11,$11,$12,$13,$14,$14,$15,$16,$17,$17,$18,$19,$1A,$1A,$1B

    ; Volume 12 (v=12): samples scaled to 0-12
    .byte $10,$11,$12,$12,$13,$14,$15,$16,$16,$17,$18,$19,$1A,$1A,$1B,$1C

    ; Volume 13 (v=13): samples scaled to 0-13
    .byte $10,$11,$12,$13,$13,$14,$15,$16,$17,$18,$19,$1A,$1A,$1B,$1C,$1D

    ; Volume 14 (v=14): samples scaled to 0-14
    .byte $10,$11,$12,$13,$14,$15,$16,$17,$17,$18,$19,$1A,$1B,$1C,$1D,$1E

    ; Volume 15 (v=15): samples scaled to 0-15
    .byte $10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$1A,$1B,$1C,$1D,$1E,$1F

.endif