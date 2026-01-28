# Proposal: Dual Channel Multiplexing (Interleaved)

## 1. Overview
This proposal outlines the implementation of a **Dual Channel Multiplexing** mode.
This mode maintains the use of **two POKEY channels** (AUDC1 + AUDC2) for higher fidelity (summing 2 output channels), but reduces the data rate by **50%** compared to standard dual-channel playback.

### Concept
Instead of updating *both* channels every frame (requiring 1 byte/frame), we interleave the updates:
-   **Even Frames (T)**: Update **AUDC1** only. (AUDC2 holds previous value).
-   **Odd Frames (T+1)**: Update **AUDC2** only. (AUDC1 holds value from T).

This allows us to pack the updates for `[AUDC1(T), AUDC2(T+1)]` into a **single byte**.

## 2. CLI Updates

### Arguments
- Reuse `--channels 2` (Default).
- New Argument: `--multiplex` (or `--interleave`?)
  -   Proposal: `--multiplex on` (Default `off`).
  -   Usage: `python -m pokey_vq input.wav --channels 2 --multiplex on`

### Logic
- If `multiplex=on`:
  -   Requires `channels=2`.
  -   Pass `multiplex=True` to `MADSExporter`.

## 3. GUI Updates (`pokey_vq/gui/components/param_panel.py`)

### UI Elements
- **Layout**: Add "Multiplexing" checkbox under Advanced or Output Control.
- **Label**: "Multiplexed Dual Channel (50% Size)"
- **Tooltip**: "Updates one channel per frame alternately. Halves data size but may introduce zipper noise."

## 4. Encoder / Exporter (`mads_exporter.py`)

### Packing Logic (Multiplexed)
The `export` method needs to stride through the codebook entries differently.

#### Input Data
Stream of vectors: `V0, V1, V2, V3...` where each `V` maps to a pair `(Ch1, Ch2)`.
*   Note: The Encoder *optimally* selects `V` assuming both channels update.
*   **Correction**: For multiplexing, the encoder should ideally know about the hold behavior. However, for a simple post-process packing:
    -   Frame T (Even): Take `V_even.Ch1`.
    -   Frame T+1 (Odd): Take `V_odd.Ch2`.

#### Packing (Standard Size)
-   **Byte Structure**: `[ High: AUDC2(Next) | Low: AUDC1(Curr) ]`
-   **Process**:
    1.  Iterate `i` from 0 to Length-2, step 2.
    2.  `Val1 = Codebook[Indices[i]].Ch1` (Low Nibble)
    3.  `Val2 = Codebook[Indices[i+1]].Ch2` (High Nibble)
    4.  `Packed = (Val2 << 4) | (Val1 & 0x0F)`
    5.  Append `Packed` to Blob.

#### Speed Optimization (Interleaved/FAST)
Similar to Single Channel mode, we can use LUTs to speed up the "High Nibble" extraction for the second frame.
-   **Data Stream**: Same Packed Byte.
-   **LUT_HI**: `Table[b] = (b >> 4) | AUDC2_MASK` (Pre-shifted and OR'd with AUDC2 register mask aka Volume Only bit).
-   **LUT_LO**: `Table[b] = (b & 0x0F) | AUDC1_MASK`.

## 5. Player Implementation

### Configuration (`VQ_CFG.asm`)
-   Add `MULTIPLEX = 1` definition.

### Playback Routine (`play_routine.asm`)

#### Concept
We need a "Phase" state (0 or 1).
-   **Phase 0 (Even)**: Read Byte. Extract Low Nibble. Update AUDC1. **Keep Pointer**.
-   **Phase 1 (Odd)**: Read Byte. Extract High Nibble. Update AUDC2. **Inc Pointer**.

#### Implementation Draft
```assembly
    .ifdef MULTIPLEX
        ; --- DUAL CHANNEL MULTIPLEXED ---
        ; Byte: [AUDC2(T+1) | AUDC1(T)]
        
        lda mux_phase
        beq do_mux_phase_0
        
    do_mux_phase_1:
        ; Update AUDC2 (High Nibble)
        ldy #0
        lda (sample_ptr),y
        
        .ifdef OPTIMIZE_SPEED
            tax
            lda LUT_HI,x   ; Pre-shifted + Masked
        .else
            lsr @ : lsr @ : lsr @ : lsr @
            ora #AUDC2_MASK
        .endif
        
        sta AUDC2
        
        ; Advance Pointer (Byte fully consumed)
        inc sample_ptr
        bne :+
        inc sample_ptr+1
    :
        lda #0
        sta mux_phase
        rts

    do_mux_phase_0:
        ; Update AUDC1 (Low Nibble)
        ldy #0
        lda (sample_ptr),y
        
        .ifdef OPTIMIZE_SPEED
            tax
            lda LUT_LO,x   ; Masked + AUDC1 Bit
        .else
            and #$0F
            ora #AUDC1_MASK
        .endif
        
        sta AUDC1
        
        ; Switch to Phase 1 (Next IRQ)
        inc mux_phase
        rts
        
    .endif
```

## 6. Verification & Risky Areas

### Zipper Noise
Since one channel holds its value while the other updates, wide jumps in volume might sound "rougher" than simultaneous updates, but probably negligible at higher playback rates.
*   **Mitigation**: The `--smoothness` parameter in the encoder becomes very important here to prevent large jumps between frames.

### Speed Optimization (LUTs)
-   Standard: `LSR` x4 is slow (8 cycles).
-   Optimization: `LDA LUT_HI,x` (4 cycles) is much faster.
-   **Requirement**: Two 256-byte tables (`LUT_LO`, `LUT_HI`) to reside in memory. Total 512 bytes extra RAM usage. This is a good trade-off.

## 7. Next Steps
1.  Implement CLI switch `--multiplex`.
2.  Implement Exporter Logic (Stride 2 packing).
3.  Implement Player Logic (`play_routine.asm`).
