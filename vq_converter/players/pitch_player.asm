; ==========================================================================
; POKEY PITCH PLAYER - FIXED VERSION
; ==========================================================================
; Interactive VQ Player with Real-Time Pitch Control.
; Implements a Piano-like interface for playing samples at different pitches.
;
; Use Case: Interactive Music Apps, Dynamic Sound Effects.
; Requirements: MULTI_SAMPLE=1, PITCH_CONTROL=1 in VQ_CFG.asm
;
; Supported Data Formats:
;   - CHANNELS=1: Nibble-packed (8 bytes per 16-sample vector)
;   - CHANNELS=2, no USE_FAST_CPU: Nibble-packed (16 bytes per 16 samples)
;   - CHANNELS=2, USE_FAST_CPU: Interleaved pre-masked (32 bytes per 16 samples)
;
; IMPORTANT: USE_FAST_CPU for CHANNELS=2 requires encoder fast=True setting!
; ==========================================================================

    icl "common/atari.inc"
    icl "common/zeropage.inc"
    icl "common/macros.inc"
    icl "common/copy_os_ram.asm"

    ; Load Configuration
    icl "VQ_CFG.asm"
    
    ; Enforce Configuration
    .ifndef MULTI_SAMPLE
        .error "pitch_player.asm requires MULTI_SAMPLE=1"
    .endif
    .ifndef PITCH_CONTROL
        .error "pitch_player.asm requires PITCH_CONTROL=1"
    .endif
    .ifndef ALGO_FIXED
        .error "pitch_player.asm requires ALGO_FIXED=1"
    .endif
    .if MIN_VECTOR != MAX_VECTOR
        .error "pitch_player.asm requires fixed vector size (MIN_VECTOR must equal MAX_VECTOR)"
    .endif
    .if MIN_VECTOR < 2 || MIN_VECTOR > 16
        .error "pitch_player.asm requires vector size between 2 and 16"
    .endif
    .if (MIN_VECTOR & 1) != 0
        .error "pitch_player.asm requires even vector size (2, 4, ... 16)"
    .endif

    ORG $2000

; ==========================================================================
; DISPLAY LIST DATA
; ==========================================================================
text_to_print:
    dta d"Q-P=SAMPLE 1-4=OCT ZXCVBNM=NOTE  "
octave_display:
    dta d"1"  ; Default octave
note_display:
    dta d"C "  ; Default note

dlist:
    .byte $70,$70,$70
    .byte $42,<text_to_print,>text_to_print
    .byte $70,$70
    .byte $41,<dlist,>dlist

; ==========================================================================
; VARIABLES (UI specific)
; ==========================================================================
current_octave:   .byte 0
current_semitone: .byte 0
playing_sample:   .byte $FF
playing_note:     .byte $FF
vector_offset:    .byte 0     ; Current sample position within vector (0-15)

; ==========================================================================
; MAIN ENTRY
; ==========================================================================
start:
    sei
    ldx #$FF
    txs
    
    ; Disable System IRQ
    lda #0
    sta NMIEN
    sta IRQEN
    sta DMACTL
    lda #$FE
    sta PORTB
    ; CopyOSRomToRam called via INI segment automatically

    ; Interrupt Vector Setup
    lda #<nmi
    sta $FFFA
    lda #>nmi
    sta $FFFA+1
    
    lda #<PitchVQ_IRQ
    sta $FFFE
    lda #>PitchVQ_IRQ
    sta $FFFE+1

    ; Display Setup
    lda #<dlist
    sta DLISTL
    lda #>dlist
    sta DLISTH
    lda #34
    sta DMACTL
    lda #$C0
    sta NMIEN
    
    ; Keyboard Init
    lda #0
    sta SKCTL
    lda #3
    sta SKCTL
    
    ; Init internal state
    lda #$FF
    sta sample_finished
    sta playing_sample
    sta playing_note
    
    ; Default Selection
    lda #0
    sta current_octave
    sta current_semitone
    sta current_sample
    jsr update_display
    
    cli

; ==========================================================================
; MAIN LOOP
; ==========================================================================
main_loop:
    ; UI Color - indicates playback state
    lda sample_finished
    bne show_idle_pitch
    lda #$40              ; Green while playing
    sta COLBK
    jmp check_input_pitch
show_idle_pitch:
    lda #$20              ; Dark when idle
    sta COLBK

check_input_pitch:
    lda SKSTAT
    and #4
    bne main_loop
    
    lda KBCODE
    
    ; --- PIANO LOGIC ---
    
    ; 1. Check Samples (Q-P)
    ldx #9
search_sample:
    cmp sample_key_table,x
    beq found_sample
    dex
    bpl search_sample
    
    ; 2. Check Octaves (1-4)
    ldx #3
search_octave:
    cmp octave_key_table,x
    beq found_octave
    dex
    bpl search_octave
    
    ; 3. Check White Keys
    ldx #6
search_white:
    cmp white_key_table,x
    beq found_white
    dex
    bpl search_white
    
    ; 4. Check Black Keys
    ldx #4
search_black:
    cmp black_key_table,x
    beq found_black
    dex
    bpl search_black
    
    jmp main_loop

found_sample:
    stx current_sample
    jmp play_current

found_octave:
    stx current_octave
    jsr update_display
    jmp main_loop

found_white:
    lda white_semitones,x
    sta current_semitone
    jsr update_display
    jmp play_current

found_black:
    lda black_semitones,x
    sta current_semitone
    jsr update_display
    jmp play_current

play_current:
    ; Calculate total note index
    ldx current_octave
    lda octave_base,x
    clc
    adc current_semitone
    tax ; X = Note (0-47)
    
    ; Debounce / Retrigger Check
    cmp playing_note
    bne force_trigger
    
    ldy current_sample
    cpy playing_sample
    bne force_trigger
    
    ldy sample_finished
    bne force_trigger
    
    jmp main_loop ; Already playing this note/sample

force_trigger:
    stx playing_note
    lda current_sample
    sta playing_sample
    
    ; Call Engine: Play Note
    ; A = Sample, X = Note
    jsr PitchVQ_PlayNote
    jmp main_loop

nmi:
    rti

update_display:
    lda current_octave
    clc
    adc #$11
    sta octave_display
    ldx current_semitone
    lda note_names,x
    sta note_display
    rts

; ==========================================================================
; ENGINE API
; ==========================================================================

; PitchVQ_PlayNote: A=Sample, X=Note
PitchVQ_PlayNote:
    pha
    jsr PitchVQ_SetPitch
    pla
    jmp PitchVQ_Init        ; Tail call optimization

; PitchVQ_SetPitch: X=Note (0-47)
PitchVQ_SetPitch:
    lda NOTE_PITCH_LO,x
    sta pitch_step
    lda NOTE_PITCH_HI,x
    sta pitch_step+1
    lda #0
    sta pitch_frac
    sta pitch_int
    rts

; PitchVQ_Init: A=Sample number
PitchVQ_Init:
    ; Bounds check - prevent reading garbage from tables
    cmp #SAMPLE_COUNT
    bcc @sample_valid
    ; Invalid sample number - flag error
    lda #$FF
    sta sample_finished
    rts
    
@sample_valid:
    tax
    
    ; Load stream pointers from SAMPLE_DIR
    lda SAMPLE_START_LO,x
    sta stream_ptr
    lda SAMPLE_START_HI,x
    sta stream_ptr+1
    lda SAMPLE_END_LO,x
    sta stream_end
    lda SAMPLE_END_HI,x
    sta stream_end+1
    
    ; Reset state
    lda #0
    sta sample_finished
    sta vector_offset       ; Start at sample 0 within first vector
    
    ; Initialize POKEY hardware
    jsr Pokey_Init
    
    ; Start timer
    lda #IRQ_MASK
    sta IRQEN
    sta STIMER
    rts

; ==========================================================================
; POKEY INITIALIZATION
; ==========================================================================
Pokey_Init:
    ; Clear IRQEN first (prevent spurious IRQs)
    lda #0
    sta IRQEN
    
    ; Enter initialization mode
    sta SKCTL
    
    ; CRITICAL FIX: Use $10 (volume-only mode, volume=0) for true silence
    ; Using $00 would activate polynomial noise generation!
    lda #$10
    sta AUDC1
    sta AUDC2
    sta AUDC3
    sta AUDC4
    
    ; Set timer frequency
    lda #AUDF1_VAL
    sta AUDF1
    sta AUDF2
    sta AUDF3
    sta AUDF4
    
    ; Set audio control
    lda #AUDCTL_VAL
    sta AUDCTL
    
    ; Exit initialization mode
    lda #$03
    sta SKCTL
    
    ; Enable IRQs
    lda #IRQ_MASK
    sta IRQEN
    rts

; ==========================================================================
; IRQ HANDLER
; ==========================================================================
; Flow: Output at CURRENT position, THEN advance for next IRQ.
; This ensures sample 0 is played on the first IRQ.
; ==========================================================================
PitchVQ_IRQ:
    sta irq_save_a
    stx irq_save_x
    sty irq_save_y
    
    ; ACK IRQ (reset timer)
    lda #0
    sta IRQEN
    lda #IRQ_MASK
    sta IRQEN
    
    ; Check if playback stopped
    lda sample_finished
    bne @irq_done

    ; --- STEP 1: OUTPUT sample at current position ---
    ldy #0
    lda (stream_ptr),y      ; Fetch codebook index
    tax                     ; X = codebook index
    jsr Output_Sample

    ; --- STEP 2: Calculate pitch advance ---
    clc
    lda pitch_frac
    adc pitch_step          ; Add low byte of pitch step
    sta pitch_frac
    lda pitch_int
    adc pitch_step+1        ; Add high byte with carry
    sta pitch_int
    
    ; If pitch_int is 0, we don't advance (for sub-1.0 pitches)
    beq @irq_done
    
    ; --- STEP 3: Advance vector_offset ---
    clc
    lda vector_offset
    adc pitch_int           ; Add accumulated samples to advance
    sta vector_offset
    
    ; Clear pitch_int for next IRQ
    lda #0
    sta pitch_int
    
    ; --- STEP 4: Handle Vector Boundary Crossing ---
@check_boundary:
    lda vector_offset
    cmp #MIN_VECTOR
    bcc @irq_done           ; Still within current vector, done
    
    ; Crossed vector boundary - advance to next codebook entry
    sec
    sbc #MIN_VECTOR
    sta vector_offset
    
    ; Advance stream_ptr (move to next codebook index)
    inc stream_ptr
    bne @check_end
    inc stream_ptr+1
    
@check_end:
    ; 16-bit comparison: stream_ptr >= stream_end?
    lda stream_ptr+1
    cmp stream_end+1
    bcc @check_more         ; Hi < End_Hi: might need more advancing
    bne @finished           ; Hi > End_Hi: past the end, done
    lda stream_ptr
    cmp stream_end
    bcc @check_more         ; Lo < End_Lo: might need more advancing
    ; Lo >= End_Lo: at or past end, done
    
@finished:
    lda #$FF
    sta sample_finished
    ; Set silence (volume-only mode, volume=0)
    lda #$10
    sta AUDC1
.if CHANNELS == 2
    sta AUDC2
.endif
    jmp @irq_done

@check_more:
    ; At very high pitches, we might advance multiple vectors per IRQ
    ; Check if we still need to advance
    lda vector_offset
    cmp #MIN_VECTOR
    bcs @check_boundary     ; Still >= 16, advance more
    ; Fall through to done
    
@irq_done:
    lda irq_save_a
    ldx irq_save_x
    ldy irq_save_y
    rti

; ==========================================================================
; OUTPUT ROUTINES - Conditional Assembly Based on Mode
; ==========================================================================
; Input: X = codebook index, vector_offset = sample position within vector (0-15)

Output_Sample:

.if CHANNELS == 1
    ; =========================================================
    ; SINGLE CHANNEL MODE
    ; =========================================================

    .ifdef USE_FAST_CPU
        ; --- FAST / BYTE MODE ---
        ; 1 byte per sample (Pre-masked $10)
        ; Vector blobs are fully expanded (16 bytes per 16 samples)
         
        lda vector_offset
        clc
        adc VQ_LO,x
        sta sample_ptr
        lda VQ_HI,x
        adc #0
        sta sample_ptr+1
        
        ldy #0
        lda (sample_ptr),y
        sta AUDC1
        rts
        
    .else
        ; --- PACKED NIBBLE MODE ---
        ; Data Format: Nibble-packed, 8 bytes per 16-sample vector
        ; Byte n contains: [sample 2n+1 : sample 2n] (high:low nibbles)
        
        ; Calculate byte address = VQ_base + (vector_offset / 2)
        lda vector_offset
        lsr                     ; A = byte offset within vector (0-7)
        clc
        adc VQ_LO,x             ; Add to codebook base low byte
        sta sample_ptr
        lda VQ_HI,x
        adc #0                  ; Add carry to high byte
        sta sample_ptr+1
        
        ; Determine which nibble based on vector_offset bit 0
        ; Even samples (0,2,4...): LOW nibble
        ; Odd samples (1,3,5...): HIGH nibble
        lda vector_offset
        and #$01
        bne @high_nibble
    
    @low_nibble:
        ; Even sample: extract LOW nibble (bits 0-3)
        ldy #0
        lda (sample_ptr),y
        and #$0F
        ora #AUDC1_MASK
        sta AUDC1
        rts
    
    @high_nibble:
        ; Odd sample: extract HIGH nibble (bits 4-7)
        ldy #0
        lda (sample_ptr),y
        lsr
        lsr
        lsr
        lsr
        ora #AUDC1_MASK
        sta AUDC1
        rts
    .endif

.else ; CHANNELS == 2

    .ifdef USE_FAST_CPU
    ; =========================================================
    ; DUAL CHANNEL SPEED MODE (Interleaved)
    ; Data Format: 2 bytes per sample, pre-masked for AUDC1/AUDC2
    ; 32 bytes per 16-sample vector
    ; Requires encoder with fast=True setting!
    ; =========================================================
    
    ; Calculate byte address = VQ_base + (vector_offset * 2)
    lda vector_offset
    asl                     ; A = byte offset within vector (0-30)
    clc
    adc VQ_LO,x
    sta sample_ptr
    lda VQ_HI,x
    adc #0
    sta sample_ptr+1
    
    ; Fetch and output (data is pre-formatted with AUDC masks!)
    ldy #0
    lda (sample_ptr),y      ; AUDC1 value
    sta AUDC1
    iny
    lda (sample_ptr),y      ; AUDC2 value
    sta AUDC2
    rts

    .else
    ; =========================================================
    ; DUAL CHANNEL SIZE MODE (Packed)
    ; Data Format: 1 byte per sample, [Ch2:Ch1] nibbles
    ; 16 bytes per 16-sample vector
    ; =========================================================
    
    ; Calculate byte address = VQ_base + vector_offset
    lda vector_offset       ; 1:1 mapping, no conversion needed
    clc
    adc VQ_LO,x
    sta sample_ptr
    lda VQ_HI,x
    adc #0
    sta sample_ptr+1
    
    ; Fetch the packed byte
    ldy #0
    lda (sample_ptr),y      ; A = [Ch2 nibble : Ch1 nibble]
    tax                     ; Save in X for later
    
    ; Extract and output Ch1 (low nibble)
    and #$0F
    ora #AUDC1_MASK
    sta AUDC1
    
    ; Extract and output Ch2 (high nibble)
    txa
    lsr
    lsr
    lsr
    lsr
    ora #AUDC2_MASK
    sta AUDC2
    rts
    
    .endif ; USE_FAST_CPU
.endif ; CHANNELS

; ==========================================================================
; DATA TABLES
; ==========================================================================
octave_base:      .byte 0, 12, 24, 36
octave_key_table: .byte $1F, $1E, $1A, $18     ; Keys 1-4
sample_key_table: .byte $2F, $2E, $2A, $28, $2D, $2B, $0B, $0D, $08, $0A ; Keys Q-P
white_key_table:  .byte $17, $16, $12, $10, $15, $23, $25 ; Keys ZXCVBNM
white_semitones:  .byte 0, 2, 4, 5, 7, 9, 11   ; C D E F G A B
black_key_table:  .byte $3E, $3A, $3D, $39, $01 ; Keys SDFGH (black keys)
black_semitones:  .byte 1, 3, 6, 8, 10         ; C# D# F# G# A#
note_names:       .byte $03, $43, $04, $44, $05, $06, $46, $07, $47, $01, $41, $02

; ==========================================================================
; INCLUDES
; ==========================================================================
    ; Pitch Tables
    icl "pitch/pitch_tables.asm"
    
    ; Sample Directory
    icl "SAMPLE_DIR.asm"
    
    ; Codebook Tables
    icl "VQ_LO.asm"
    icl "VQ_HI.asm"
    icl "VQ_BLOB.asm"
    icl "VQ_INDICES.asm"

; LUT for single-channel speed optimization


    run start
