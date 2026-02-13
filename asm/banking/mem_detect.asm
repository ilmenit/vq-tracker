; ==========================================================================
; MEM_DETECT.ASM - Extended RAM Bank Detection
; ==========================================================================
; Detects available extended memory banks on Atari XL/XE systems.
; Uses write/verify/restore pattern to safely test each bank.
;
; NOTE: All labels use globally unique "mdet_" prefix because MADS @local
; labels leak across .icl includes, causing collisions with other files.
;
; Result: mem_banks_found = number of working banks
;         mem_bank_portb = PORTB values for each detected bank
; ==========================================================================

PORTB_ADDR = $D301
TEST_ADDR  = $4000            ; Address in bank window to test
TEST_VAL   = $A5              ; Test pattern
TEST_VAL2  = $5A              ; Inverse pattern (to catch bus floating)

; OS shadow registers (VBI copies these to hardware every frame)
SDLSTL = $0230                ; Display list pointer low
SDLSTH = $0231                ; Display list pointer high
SDMCTL = $022F                ; DMA control
COLOR1 = $02C5                ; COLPF1 shadow
COLOR2 = $02C6                ; COLPF2 shadow
COLOR4 = $02C8                ; COLBK shadow

; PORTB values for all 64 possible banks (dBANK table)
dBANK:
    .byte $E3,$C3,$A3,$83,$63,$43,$23,$03
    .byte $E7,$C7,$A7,$87,$67,$47,$27,$07
    .byte $EB,$CB,$AB,$8B,$6B,$4B,$2B,$0B
    .byte $EF,$CF,$AF,$8F,$6F,$4F,$2F,$0F
    .byte $ED,$CD,$AD,$8D,$6D,$4D,$2D,$0D
    .byte $E9,$C9,$A9,$89,$69,$49,$29,$09
    .byte $E5,$C5,$A5,$85,$65,$45,$25,$05
    .byte $E1,$C1,$A1,$81,$61,$41,$21,$01

; Storage for detected banks
mem_banks_found: .byte 0
mem_bank_portb:                ; Up to 64 PORTB values
    .ds 64

; ==========================================================================
; MEM_DETECT - Detect extended memory banks
; ==========================================================================
mem_detect:
    lda #0
    sta mem_banks_found
    tax                         ; X = bank test index (0-63)

mdet_loop:
    lda PORTB_ADDR
    pha                         ; save current PORTB
    
    lda dBANK,x
    sta PORTB_ADDR              ; switch to candidate bank
    
    lda TEST_ADDR
    pha                         ; save original byte
    
    lda #TEST_VAL
    sta TEST_ADDR
    lda TEST_ADDR
    cmp #TEST_VAL
    bne mdet_no_bank
    
    lda #TEST_VAL2
    sta TEST_ADDR
    lda TEST_ADDR
    cmp #TEST_VAL2
    bne mdet_no_bank
    
    ; Bank exists - store its PORTB value
    ldy mem_banks_found
    lda dBANK,x
    sta mem_bank_portb,y
    inc mem_banks_found
    
mdet_no_bank:
    pla
    sta TEST_ADDR               ; restore original byte
    pla
    sta PORTB_ADDR              ; restore PORTB
    
    inx
    cpx #64
    bcc mdet_loop
    
    rts

; ==========================================================================
; MEM_VALIDATE - Verify that the specific banks we need are available
; ==========================================================================
; Probes banks 0..REQUIRED_BANKS-1 using dBANK[N] PORTB values.
; Stronger than a count check: catches non-contiguous memory where
; the first N banks are dead but later banks exist.
; ==========================================================================
mem_validate:
    ldx #0
mdet_validate_loop:
    cpx #REQUIRED_BANKS
    bcs mdet_validate_pass      ; All needed banks verified

    lda PORTB_ADDR
    pha                         ; save current PORTB

    lda dBANK,x
    sta PORTB_ADDR              ; switch to candidate bank

    lda TEST_ADDR
    pha                         ; save original byte at $4000

    lda #TEST_VAL
    sta TEST_ADDR
    lda TEST_ADDR
    cmp #TEST_VAL
    bne mdet_validate_bad

    lda #TEST_VAL2
    sta TEST_ADDR
    lda TEST_ADDR
    cmp #TEST_VAL2
    bne mdet_validate_bad

    ; Bank OK - restore and check next
    pla
    sta TEST_ADDR               ; restore original byte
    pla
    sta PORTB_ADDR              ; restore PORTB
    inx
    jmp mdet_validate_loop

mdet_validate_bad:
    pla
    sta TEST_ADDR               ; restore original byte
    pla
    sta PORTB_ADDR              ; restore PORTB
    jmp mem_validate_fail

mdet_validate_pass:
    rts

mem_validate_fail:
    jsr mem_error_screen
    jmp *                       ; Halt forever

; ==========================================================================
; MEM_ERROR_SCREEN - Display error and freeze
; ==========================================================================
; Writes BOTH OS shadow registers (for persistence across VBI frames)
; and hardware registers (for immediate visibility).
; ==========================================================================
mem_error_screen:
    ; Briefly disable NMI to prevent VBI interference during setup
    lda #0
    sta $D40E                   ; NMIEN = 0

    ; Silence audio
    sta $D208                   ; AUDCTL = 0
    sta $D200                   ; AUDF1 = 0
    sta $D201                   ; AUDC1 = 0

    ; Set display list via OS shadow registers (persists across VBI)
    lda #<mem_err_dl
    sta SDLSTL
    lda #>mem_err_dl
    sta SDLSTH

    ; Set colors via OS shadow registers
    lda #$00
    sta COLOR4                  ; COLBK = black
    lda #$0E
    sta COLOR1                  ; COLPF1 = white
    lda #$46
    sta COLOR2                  ; COLPF2 = dark red background

    ; Enable display via shadow
    lda #$22
    sta SDMCTL                  ; DL DMA + normal playfield

    ; Also write hardware directly for immediate effect (before VBI fires)
    lda #<mem_err_dl
    sta $D402                   ; DLISTL
    lda #>mem_err_dl
    sta $D403                   ; DLISTH
    lda #$00
    sta $D01A                   ; COLBK
    lda #$0E
    sta $D016                   ; COLPF1
    lda #$46
    sta $D017                   ; COLPF2
    lda #$22
    sta $D400                   ; DMACTL

    ; Format digit display: "NEED: NN"
    lda #REQUIRED_BANKS
    jsr mdet_byte_to_digits
    sta mem_err_need_digits+1
    stx mem_err_need_digits

    ; Format digit display: "FOUND: NN"
    lda mem_banks_found
    jsr mdet_byte_to_digits
    sta mem_err_found_digits+1
    stx mem_err_found_digits

    ; Re-enable NMI so VBI maintains display from shadow registers
    lda #$C0
    sta $D40E                   ; NMIEN = VBI + DLI

    rts

; ==========================================================================
; Convert byte in A to two screen-code digit chars
; Returns: X = tens digit (screen code), A = ones digit (screen code)
; ==========================================================================
mdet_byte_to_digits:
    ldx #$10                    ; Screen code '0' for tens
    sec
mdet_btd_sub:
    sbc #10
    bcc mdet_btd_done
    inx
    jmp mdet_btd_sub
mdet_btd_done:
    adc #10                     ; undo last subtraction
    ora #$10                    ; convert to screen code digit
    rts

; ==========================================================================
; Error screen display data
; ==========================================================================

; Display list for error screen (ANTIC mode 2 = 40-column text)
mem_err_dl:
    .byte $70,$70,$70           ; 24 blank lines
    .byte $47                   ; Mode 2 + LMS
    .word mem_err_line1
    .byte $07                   ; Mode 2
    .byte $07                   ; Mode 2
    .byte $70                   ; 8 blank lines
    .byte $47                   ; Mode 2 + LMS
    .word mem_err_line4
    .byte $07                   ; Mode 2
    .byte $41                   ; JVB
    .word mem_err_dl

; Text lines in screen codes (dta d converts ATASCII to ANTIC screen codes)
;                          1234567890123456789012345678901234567890
mem_err_line1:
    dta d"  INSUFFICIENT EXTENDED MEMORY          "
    dta d"                                        "
    dta d"  THIS SONG REQUIRES EXTENDED RAM       "
mem_err_line4:
mem_err_need_txt:
    dta d"  NEED: "
mem_err_need_digits:
    dta d"??"
    dta d" BANKS                          "
mem_err_found_txt:
    dta d"  FOUND: "
mem_err_found_digits:
    dta d"??"
    dta d" BANKS                         "
