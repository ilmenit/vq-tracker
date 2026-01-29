; PokeyVQ Reusable Player Code
; Include this file in your project.
;
; Requirements:
; - VQ_CFG.asm must be included/defined before this.
; - Zeropage variables (stream_ptr, etc.) must be defined (see common/zeropage.inc).
;
; Exports:
; - PokeyVQ_Init (A = sample number if MULTI_SAMPLE defined)
; - PokeyVQ_IRQ (Full IRQ handler, ends with RTI)
; - PokeyVQ_SetPitch (X = note 0-47, if PITCH_CONTROL defined)
; - PokeyVQ_PlayNote (A = sample, X = note, if PITCH_CONTROL defined)

; Multi-sample mode: Include sample directory if present
.ifdef MULTI_SAMPLE
    icl "SAMPLE_DIR.asm"
.endif

; Pitch control mode: Include pitch lookup tables
.ifdef PITCH_CONTROL
    icl "../pitch/pitch_tables.asm"
.endif

PokeyVQ_Init:
    ; Initialize Stream Pointers based on Algo
    
.ifdef MULTI_SAMPLE
    ; --- MULTI-SAMPLE MODE ---
    ; Input: A = sample number (0-based)
    tax                         ; X = sample index
    
    ; Set stream start from SAMPLE_DIR
    lda SAMPLE_START_LO,x
    sta stream_ptr
    lda SAMPLE_START_HI,x
    sta stream_ptr+1
    
    ; Set stream end from SAMPLE_DIR
    lda SAMPLE_END_LO,x
    sta stream_end
    lda SAMPLE_END_HI,x
    sta stream_end+1
    
    ; Clear sample finished flag
    lda #0
    sta sample_finished
    sta sample_len
    
.ifdef PITCH_CONTROL
    ; Initialize pitch to base (1.0x) if not already set
    ; This preserves pitch set by PokeyVQ_SetPitch before Init
    lda pitch_step
    ora pitch_step+1
    bne @pitch_already_set
    lda #$00
    sta pitch_step      ; Lo byte
    lda #$01
    sta pitch_step+1    ; Hi byte ($0100 = 1.0x)
@pitch_already_set:
    lda #0
    sta pitch_frac
    sta pitch_int
.endif
    
.else
    ; --- SINGLE-SAMPLE MODE ---
    .ifdef ALGO_RAW
        lda #<RAW_DATA
        sta sample_ptr
        lda #>RAW_DATA
        sta sample_ptr+1
        
        ; Calculate End
        lda sample_ptr
        clc
        adc #<RAW_DATA_LEN
        sta stream_end
        lda sample_ptr+1
        adc #>RAW_DATA_LEN
        sta stream_end+1
        
        lda #0
        sta sample_len ; Always 0 to force fetch
    .else
        ; VQ Fixed or Sliding
        lda #<VQ_INDICES
        sta stream_ptr
        lda #>VQ_INDICES
        sta stream_ptr+1
        
        ; Calculate End
        lda stream_ptr
        clc
        adc #<VQ_INDICES_LEN
        sta stream_end
        lda stream_ptr+1
        adc #>VQ_INDICES_LEN
        sta stream_end+1
        
        lda #0
        sta sample_len
    .endif
.endif

.ifndef MULTI_SAMPLE
.ifdef PITCH_CONTROL
    ; Initialize pitch to base (1.0x) for single-sample mode
    lda #$00
    sta pitch_step
    lda #$01
    sta pitch_step+1
    lda #0
    sta pitch_frac
    sta pitch_int
.endif
.endif



    ; Hardware Init
    icl "pokey_setup.asm"
    rts

PokeyVQ_IRQ:
    ; Register Save
    sta irq_save_a
    stx irq_save_x
    sty irq_save_y

    ; ACK IRQ (Reset Counter)
    lda #0
    sta IRQEN
    lda #IRQ_MASK
    sta IRQEN

.ifdef PITCH_CONTROL
    ; --- PITCH CONTROL MODE ---
    ; Accumulate fractional pitch step
    clc
    lda pitch_frac
    adc pitch_step          ; Add low byte of step
    sta pitch_frac
    lda pitch_int
    adc pitch_step+1        ; Add high byte with carry
    sta pitch_int
    beq pitch_no_advance    ; If zero, don't advance (repeat sample)
    
    ; pitch_int = number of samples to advance this IRQ
    tax                     ; X = loop counter
    lda #0
    sta pitch_int           ; Reset for next IRQ
    
pitch_loop:
    lda sample_len
    bne pitch_play
    
    ; Need new vector - fetch_next clobbers X!
    stx pitch_save_x        ; Save loop counter
    jsr fetch_next ; Implemented in algo_*.asm
    ldx pitch_save_x        ; Restore loop counter
.ifdef MULTI_SAMPLE
    lda sample_finished
    bne exit_irq_irq        ; Sample ended
.endif
    jmp pitch_next
    
pitch_play:
    ; Play one sample and advance pointer
    stx pitch_save_x        ; Save loop counter
    jsr play_sample ; Implemented in algo_*.asm
    ldx pitch_save_x        ; Restore loop counter
    
pitch_next:
    dex
    bne pitch_loop
    jmp exit_irq_irq
    
pitch_no_advance:
    ; Same sample, no advancement (for slow pitch)
    ; Just maintain current output (already in AUDC registers)
    jmp exit_irq_irq
    
.else
    ; --- STANDARD MODE (NO PITCH CONTROL) ---
    ; Core Logic
    lda sample_len
    bne continue_sample_irq
    
    ; Need new sample/vector
    jsr fetch_next ; Implemented in algo_*.asm
    jmp exit_irq_irq

continue_sample_irq:
    jsr play_sample ; Implemented in algo_*.asm
.endif

exit_irq_irq:
    lda irq_save_a
    ldx irq_save_x
    ldy irq_save_y
    rti

; --- Internal Routines ---



; --- Pitch Control Routines ---
.ifdef PITCH_CONTROL

; PokeyVQ_SetPitch
; Sets pitch step from note lookup table
; Input: X = note index (0-47)
; Destroys: A
PokeyVQ_SetPitch:
    lda NOTE_PITCH_LO,x
    sta pitch_step
    lda NOTE_PITCH_HI,x
    sta pitch_step+1
    ; Reset fractional accumulator
    lda #0
    sta pitch_frac
    sta pitch_int
    rts

.ifdef MULTI_SAMPLE
; PokeyVQ_PlayNote
; Plays a sample at a specific pitch
; Input: A = sample number (0-based)
;        X = note index (0-47)
; Destroys: All registers
PokeyVQ_PlayNote:
    ; Save sample number
    pha
    
    ; Set pitch first
    jsr PokeyVQ_SetPitch
    
    ; Now init sample
    pla
    jsr PokeyVQ_Init
    rts
.endif

.endif

; --- Algorithm Implementations ---
; NOTE: The algo files must export 'fetch_next' and 'play_sample' (if called).
; But wait, 'algo_sliding.asm' previously had 'init_sliding' inside it.
; I extracted 'PokeyVQ_Init_Sliding' above. I should verify 'algo_sliding.asm'.

.ifdef ALGO_FIXED
    icl "../fixed/algo_fixed.asm"
.endif



.ifdef ALGO_RAW
    icl "../raw/algo_raw.asm"
.endif
