# Atari 6502 Tracker - Export Data Format

## Overview

This document describes the binary/ASM export format for songs created in the Music Tracker.
The format is optimized for efficient playback on 6502 processors with minimal memory usage.

## Design Principles

1. **Event-based storage**: Only note events are stored, not empty rows
2. **Variable-length encoding**: Use high bit flags to skip unchanged inst/vol
3. **Parallel arrays**: Fast indexed access using single-byte indices
4. **No metadata**: Title, author etc. not included in binary - pure playback data
5. **8-bit friendly**: All indices fit in single bytes, easy flag checking with BPL/BMI

## Data Structures

### Song Header

```asm
SONG_LENGTH:     .byte N          ; Number of songlines (1-255)
```

### Songline Arrays (parallel, indexed by songline number)

```asm
SONG_SPEED:      .byte s0,s1,s2...    ; Speed (VBLANKs per row) for each songline
SONG_PTN_CH0:    .byte p0,p1,p2...    ; Pattern index for channel 0
SONG_PTN_CH1:    .byte p0,p1,p2...    ; Pattern index for channel 1
SONG_PTN_CH2:    .byte p0,p1,p2...    ; Pattern index for channel 2
```

### Pattern Directory

```asm
PATTERN_COUNT:   .byte M              ; Number of patterns (1-255)
PATTERN_LEN:     .byte l0,l1,l2...    ; Row count for each pattern (1-255)
PATTERN_PTR_LO:  .byte <p0,<p1,<p2... ; Low byte of pattern data address
PATTERN_PTR_HI:  .byte >p0,>p1,>p2... ; High byte of pattern data address
```

### Pattern Event Data (Variable-Length Encoding)

Each pattern is a sequence of variable-length events, terminated by $FF:

```
Event format:
  BYTE 0: row      - Row number (0-254), $FF = end of pattern
  BYTE 1: note     - Bit 7: inst follows, Bits 0-5: note (0-36)
  BYTE 2: [inst]   - Optional. Bit 7: vol follows, Bits 0-6: instrument (0-127)
  BYTE 3: [vol]    - Optional. Bits 0-3: volume (0-15)
```

**Encoding Rules:**
- If `note & $80 == 0`: No instrument/volume bytes follow (use last values)
- If `note & $80 != 0`: Instrument byte follows
  - If `inst & $80 == 0`: No volume byte (use last value)
  - If `inst & $80 != 0`: Volume byte follows

**Event Sizes:**
| Scenario | Bytes | Description |
|----------|-------|-------------|
| Same inst+vol | 2 | row, note |
| New inst, same vol | 3 | row, note\|$80, inst |
| Same inst, new vol | 4 | row, note\|$80, inst\|$80, vol (inst repeated) |
| New inst+vol | 4 | row, note\|$80, inst\|$80, vol |

Note: When only volume changes, we must still include the instrument byte
(with the same value) because volume can only follow instrument in this format.

**Special Values:**
- `row = $FF` - End of pattern marker
- `note & $3F = 0` - Note off (silence channel)
- `note & $3F = 1-36` - Actual notes (C-1=1 through B-3=36)

**Pitch Table Mapping:**
When playing, the ASM code converts notes 1-36 to pitch table indices 0-35:

| GUI Note | Export Value | ASM Index | Pitch Multiplier |
|----------|--------------|-----------|------------------|
| C-1      | 1            | 0         | 1.0x (original)  |
| C-2      | 13           | 12        | 2.0x (1 octave up) |
| C-3      | 25           | 24        | 4.0x (2 octaves up) |

The pitch table uses 8.8 fixed-point values:
- Index 0: $0100 = 256 = 1.0x
- Index 12: $0200 = 512 = 2.0x
- Index 24: $0400 = 1024 = 4.0x

**Limitations:**
- Maximum pattern length is 255 rows (0-254), because $FF is reserved as end marker
- Maximum 256 patterns, 256 songlines (single-byte indices)

## Memory Layout Example

```asm
; === SONG DATA ===
SONG_LENGTH:     .byte 4              ; 4 songlines

SONG_SPEED:      .byte 6, 6, 4, 6     ; Speeds per songline
SONG_PTN_CH0:    .byte 0, 0, 1, 2     ; Channel 0 patterns
SONG_PTN_CH1:    .byte 3, 3, 3, 4     ; Channel 1 patterns  
SONG_PTN_CH2:    .byte 5, 5, 5, 5     ; Channel 2 patterns

; === PATTERN DIRECTORY ===
PATTERN_COUNT:   .byte 6              ; 6 patterns

PATTERN_LEN:     .byte 64, 64, 32, 64, 64, 64
PATTERN_PTR_LO:  .byte <PTN_0, <PTN_1, <PTN_2, <PTN_3, <PTN_4, <PTN_5
PATTERN_PTR_HI:  .byte >PTN_0, >PTN_1, >PTN_2, >PTN_3, >PTN_4, >PTN_5

; === PATTERN DATA ===
PTN_0:  ; Bass pattern - same instrument, same volume throughout
    .byte 0,  13|$80, 0|$80, 15   ; Row 0: C-2, inst 0, vol 15 (first note, all specified)
    .byte 8,  15                   ; Row 8: D-2 (same inst+vol)
    .byte 16, 17                   ; Row 16: E-2 (same inst+vol)
    .byte 24, 13                   ; Row 24: C-2 (same inst+vol)
    .byte $FF                      ; End

PTN_1:  ; Lead pattern - same inst, varying volume
    .byte 0,  25|$80, 2|$80, 15   ; Row 0: C-3, inst 2, vol 15
    .byte 4,  27|$80, 2|$80, 12   ; Row 4: D-3, inst 2, vol 12 (vol changed)
    .byte 8,  29                   ; Row 8: E-3 (same inst+vol)
    .byte $FF                      ; End

PTN_2:  ; Drums - different instruments, same volume
    .byte 0,  13|$80, 5           ; Row 0: C-2, inst 5 (kick), vol from last
    .byte 4,  13|$80, 6           ; Row 4: C-2, inst 6 (snare)
    .byte 8,  13|$80, 7           ; Row 8: C-2, inst 7 (hihat)
    .byte $FF                      ; End
```

## Playback Algorithm (Pseudocode)

```
Initialize:
    for each channel:
        last_inst[ch] = 0
        last_vol[ch] = 15

read_event(channel):
    row = read_byte()
    if row == $FF: return END_OF_PATTERN
    
    note_byte = read_byte()
    note = note_byte & $3F
    
    if note_byte & $80:          ; Instrument follows?
        inst_byte = read_byte()
        inst = inst_byte & $7F
        last_inst[ch] = inst
        
        if inst_byte & $80:      ; Volume follows?
            vol = read_byte() & $0F
            last_vol[ch] = vol
    
    return (row, note, last_inst[ch], last_vol[ch])
```

## 6502 Implementation

```asm
; Read next event for channel (ptr in trk_ptr)
; Returns: A=row ($FF=end), updates last_inst/last_vol
read_event:
    ldy #0
    lda (trk_ptr),y      ; row
    cmp #$FF
    beq @done            ; End of pattern
    sta event_row
    
    iny
    lda (trk_ptr),y      ; note byte
    sta event_note
    bpl @no_inst         ; Bit 7 clear = no instrument
    
    ; Has instrument
    iny
    lda (trk_ptr),y
    sta event_inst
    bpl @no_vol          ; Bit 7 clear = no volume
    
    ; Has volume
    iny
    lda (trk_ptr),y
    and #$0F
    sta event_vol
    iny
    jmp @advance_ptr
    
@no_vol:
    and #$7F             ; Clear flag bit from inst
    sta event_inst
    iny
    jmp @advance_ptr
    
@no_inst:
    iny                  ; Skip just row+note (2 bytes)
    
@advance_ptr:
    ; Advance trk_ptr by Y bytes
    tya
    clc
    adc trk_ptr
    sta trk_ptr
    bcc @done
    inc trk_ptr+1
@done:
    rts
```

## Size Comparison

**Example: 16 patterns, average 16 events/pattern**

| Format | Calculation | Size |
|--------|-------------|------|
| Full row storage | 3 bytes Ã— 64 rows Ã— 16 patterns | 3072 bytes |
| Fixed 4-byte events | 4 bytes Ã— 16 events Ã— 16 patterns + 16 | 1040 bytes |
| Variable-length | ~2.5 bytes Ã— 16 events Ã— 16 patterns + 16 | ~656 bytes |

**Savings vs full storage: ~79%**
**Savings vs fixed events: ~37%**

## File Naming Convention

Exported files:
- `SONG_DATA.asm` - Song structure and pattern data (variable-length)
- Player includes existing VQ files:
  - `SAMPLE_DIR.asm` - Sample pointers  
  - `VQ_*.asm` - VQ codebook and indices
