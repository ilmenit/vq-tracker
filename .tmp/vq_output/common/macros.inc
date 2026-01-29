; System Macros

    .macro SYSTEM_OFF
    lda #0
    sta NMIEN
    sei
    sta IRQEN
    lda #$FE   ; Enable RAM
    sta PORTB
    .endm

    .macro SYSTEM_ON
    lda #34    ; Enable DMA
    sta DMACTL
    lda #$C0   ; Enable NMI (VBI + DLI)
    sta NMIEN
    cli
    .endm
