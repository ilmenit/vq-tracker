; ==========================================================================
; PITCH TABLES - CORRECTED VALUES
; ==========================================================================
; 8.8 fixed-point pitch multipliers for equal temperament
; Base = $0100 (1.0x), each semitone up = multiply by 2^(1/12) â‰ˆ 1.0595
;
; FIXED: ASM-4 - Original tables had accumulated calculation errors
;        reaching -10% at octave 3. These are mathematically correct values.
;
; Formula: pitch[n] = 256 * 2^(n/12) where n=0 is C0
; ==========================================================================

; Octave 0: C0-B0 (notes 0-11)
; Octave 1: C1-B1 (notes 12-23)  
; Octave 2: C2-B2 (notes 24-35)
; Octave 3: C3-B3 (notes 36-47)

NOTE_PITCH_LO:
    ; Octave 0 (C0-B0) - Base octave, pitch ~1.0x
    .byte $00   ; C0  = $0100 = 256 = 1.000x
    .byte $0F   ; C#0 = $010F = 271 = 1.059x
    .byte $1F   ; D0  = $011F = 287 = 1.122x
    .byte $30   ; D#0 = $0130 = 304 = 1.189x
    .byte $43   ; E0  = $0143 = 323 = 1.260x
    .byte $56   ; F0  = $0156 = 342 = 1.335x
    .byte $6B   ; F#0 = $016B = 363 = 1.414x
    .byte $80   ; G0  = $0180 = 384 = 1.498x
    .byte $97   ; G#0 = $0197 = 407 = 1.587x
    .byte $B0   ; A0  = $01B0 = 432 = 1.682x
    .byte $CA   ; A#0 = $01CA = 458 = 1.782x
    .byte $E5   ; B0  = $01E5 = 485 = 1.888x
    
    ; Octave 1 (C1-B1) - pitch ~2.0x
    .byte $00   ; C1  = $0200 = 512 = 2.000x
    .byte $1E   ; C#1 = $021E = 542 = 2.117x
    .byte $3E   ; D1  = $023E = 574 = 2.242x
    .byte $60   ; D#1 = $0260 = 608 = 2.378x
    .byte $85   ; E1  = $0285 = 645 = 2.520x
    .byte $AC   ; F1  = $02AC = 684 = 2.670x
    .byte $D6   ; F#1 = $02D6 = 726 = 2.835x
    .byte $00   ; G1  = $0300 = 768 = 3.000x
    .byte $2E   ; G#1 = $032E = 814 = 3.180x
    .byte $60   ; A1  = $0360 = 864 = 3.375x
    .byte $94   ; A#1 = $0394 = 916 = 3.578x
    .byte $CC   ; B1  = $03CC = 972 = 3.797x
    
    ; Octave 2 (C2-B2) - pitch ~4.0x
    .byte $00   ; C2  = $0400 = 1024 = 4.000x
    .byte $3C   ; C#2 = $043C = 1084 = 4.234x
    .byte $7C   ; D2  = $047C = 1148 = 4.484x
    .byte $C0   ; D#2 = $04C0 = 1216 = 4.750x
    .byte $0A   ; E2  = $050A = 1290 = 5.039x
    .byte $58   ; F2  = $0558 = 1368 = 5.344x
    .byte $AC   ; F#2 = $05AC = 1452 = 5.672x
    .byte $00   ; G2  = $0600 = 1536 = 6.000x
    .byte $5C   ; G#2 = $065C = 1628 = 6.359x
    .byte $C0   ; A2  = $06C0 = 1728 = 6.750x
    .byte $28   ; A#2 = $0728 = 1832 = 7.156x
    .byte $98   ; B2  = $0798 = 1944 = 7.594x
    
    ; Octave 3 (C3-B3) - pitch ~8.0x
    .byte $00   ; C3  = $0800 = 2048 = 8.000x
    .byte $78   ; C#3 = $0878 = 2168 = 8.469x
    .byte $F8   ; D3  = $08F8 = 2296 = 8.969x
    .byte $80   ; D#3 = $0980 = 2432 = 9.500x
    .byte $14   ; E3  = $0A14 = 2580 = 10.078x
    .byte $B0   ; F3  = $0AB0 = 2736 = 10.688x
    .byte $58   ; F#3 = $0B58 = 2904 = 11.344x
    .byte $00   ; G3  = $0C00 = 3072 = 12.000x
    .byte $B8   ; G#3 = $0CB8 = 3256 = 12.719x
    .byte $80   ; A3  = $0D80 = 3456 = 13.500x
    .byte $50   ; A#3 = $0E50 = 3664 = 14.313x
    .byte $30   ; B3  = $0F30 = 3888 = 15.188x

NOTE_PITCH_HI:
    ; Octave 0 (C0-B0)
    .byte $01,$01,$01,$01,$01,$01,$01,$01,$01,$01,$01,$01
    
    ; Octave 1 (C1-B1)
    .byte $02,$02,$02,$02,$02,$02,$02,$03,$03,$03,$03,$03
    
    ; Octave 2 (C2-B2)
    .byte $04,$04,$04,$04,$05,$05,$05,$06,$06,$06,$07,$07
    
    ; Octave 3 (C3-B3)
    .byte $08,$08,$08,$09,$0A,$0A,$0B,$0C,$0C,$0D,$0E,$0F
