; ==========================================================================
; PITCH TABLES - 5 Octaves (60 Notes)
; ==========================================================================
; 8.8 fixed-point pitch multipliers for equal temperament tuning.
;
; Extended with 2 sub-octaves (0.25x, 0.5x) to support instruments
; with base_note > C-1 (e.g., MOD imports pitched at C-3).
;
; Index 0  = 0.25x (lowest pitch)
; Index 24 = 1.00x (base pitch - sample plays at POKEY rate)
; Index 48 = 4.00x (highest pitch)
;
; Formula: pitch[n] = 256 * 2^((n-24)/12)
;
; build.py computes: export_note = gui_note + PITCH_OFFSET - (base_note - 1)
; ASM player uses:  pitch_index = export_note - 1
; ==========================================================================

PITCH_OFFSET = 24


NOTE_PITCH_LO:
    ; --- Octave -1 (0.25x base) ---
    .byte $40   ; C--1  = $0040 =    64 = 0.250x
    .byte $44   ; C#-1  = $0044 =    68 = 0.265x
    .byte $48   ; D--1  = $0048 =    72 = 0.281x
    .byte $4C   ; D#-1  = $004C =    76 = 0.297x
    .byte $51   ; E--1  = $0051 =    81 = 0.315x
    .byte $55   ; F--1  = $0055 =    85 = 0.334x
    .byte $5B   ; F#-1  = $005B =    91 = 0.354x
    .byte $60   ; G--1  = $0060 =    96 = 0.375x
    .byte $66   ; G#-1  = $0066 =   102 = 0.397x
    .byte $6C   ; A--1  = $006C =   108 = 0.420x
    .byte $72   ; A#-1  = $0072 =   114 = 0.445x
    .byte $79   ; B--1  = $0079 =   121 = 0.472x

    ; --- Octave 0  (0.50x base) ---
    .byte $80   ; C-0   = $0080 =   128 = 0.500x
    .byte $88   ; C#0   = $0088 =   136 = 0.530x
    .byte $90   ; D-0   = $0090 =   144 = 0.561x
    .byte $98   ; D#0   = $0098 =   152 = 0.595x
    .byte $A1   ; E-0   = $00A1 =   161 = 0.630x
    .byte $AB   ; F-0   = $00AB =   171 = 0.667x
    .byte $B5   ; F#0   = $00B5 =   181 = 0.707x
    .byte $C0   ; G-0   = $00C0 =   192 = 0.749x
    .byte $CB   ; G#0   = $00CB =   203 = 0.794x
    .byte $D7   ; A-0   = $00D7 =   215 = 0.841x
    .byte $E4   ; A#0   = $00E4 =   228 = 0.891x
    .byte $F2   ; B-0   = $00F2 =   242 = 0.944x

    ; --- Octave 1  (1.0x base) ---
    .byte $00   ; C-1   = $0100 =   256 = 1.000x
    .byte $0F   ; C#1   = $010F =   271 = 1.059x
    .byte $1F   ; D-1   = $011F =   287 = 1.122x
    .byte $30   ; D#1   = $0130 =   304 = 1.189x
    .byte $43   ; E-1   = $0143 =   323 = 1.260x
    .byte $56   ; F-1   = $0156 =   342 = 1.335x
    .byte $6A   ; F#1   = $016A =   362 = 1.414x
    .byte $80   ; G-1   = $0180 =   384 = 1.498x
    .byte $96   ; G#1   = $0196 =   406 = 1.587x
    .byte $AF   ; A-1   = $01AF =   431 = 1.682x
    .byte $C8   ; A#1   = $01C8 =   456 = 1.782x
    .byte $E3   ; B-1   = $01E3 =   483 = 1.888x

    ; --- Octave 2  (2.0x base) ---
    .byte $00   ; C-2   = $0200 =   512 = 2.000x
    .byte $1E   ; C#2   = $021E =   542 = 2.119x
    .byte $3F   ; D-2   = $023F =   575 = 2.245x
    .byte $61   ; D#2   = $0261 =   609 = 2.378x
    .byte $85   ; E-2   = $0285 =   645 = 2.520x
    .byte $AB   ; F-2   = $02AB =   683 = 2.670x
    .byte $D4   ; F#2   = $02D4 =   724 = 2.828x
    .byte $FF   ; G-2   = $02FF =   767 = 2.997x
    .byte $2D   ; G#2   = $032D =   813 = 3.175x
    .byte $5D   ; A-2   = $035D =   861 = 3.364x
    .byte $90   ; A#2   = $0390 =   912 = 3.564x
    .byte $C7   ; B-2   = $03C7 =   967 = 3.775x

    ; --- Octave 3  (4.0x base) ---
    .byte $00   ; C-3   = $0400 =  1024 = 4.000x
    .byte $3D   ; C#3   = $043D =  1085 = 4.238x
    .byte $7D   ; D-3   = $047D =  1149 = 4.490x
    .byte $C2   ; D#3   = $04C2 =  1218 = 4.757x
    .byte $0A   ; E-3   = $050A =  1290 = 5.040x
    .byte $57   ; F-3   = $0557 =  1367 = 5.339x
    .byte $A8   ; F#3   = $05A8 =  1448 = 5.657x
    .byte $FE   ; G-3   = $05FE =  1534 = 5.993x
    .byte $59   ; G#3   = $0659 =  1625 = 6.350x
    .byte $BA   ; A-3   = $06BA =  1722 = 6.727x
    .byte $21   ; A#3   = $0721 =  1825 = 7.127x
    .byte $8D   ; B-3   = $078D =  1933 = 7.551x

NOTE_PITCH_HI:
    ; --- Octave -1 (0.25x base) ---
    .byte $00,$00,$00,$00,$00,$00,$00,$00,$00,$00,$00,$00
    ; --- Octave 0  (0.50x base) ---
    .byte $00,$00,$00,$00,$00,$00,$00,$00,$00,$00,$00,$00
    ; --- Octave 1  (1.0x base) ---
    .byte $01,$01,$01,$01,$01,$01,$01,$01,$01,$01,$01,$01
    ; --- Octave 2  (2.0x base) ---
    .byte $02,$02,$02,$02,$02,$02,$02,$02,$03,$03,$03,$03
    ; --- Octave 3  (4.0x base) ---
    .byte $04,$04,$04,$04,$05,$05,$05,$05,$06,$06,$07,$07
