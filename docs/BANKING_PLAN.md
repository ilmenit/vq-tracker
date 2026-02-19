# Extended Memory Banking — Implementation Plan

## Overview

Add support for Atari XL/XE extended RAM (128KB–1MB), allowing sample data to
be stored in 16KB banks at $4000–$7FFF. This removes the current ~40KB limit
on total sample data and enables full-length Amiga MOD samples.

## Architecture: Tebe-Style Inline Bank Switching

Based on proven approach from Tebe's 6502 MOD Player 2.3:

```
IRQ handler (per channel):
    ldx #$E3          ; SMC: PORTB value for this channel's bank
    stx PORTB          ; switch bank (6 cycles)
    ldx $4A00          ; SMC: read sample byte from bank window
    lda VOLUME,x       ; volume lookup (main RAM, always visible)
```

The bank PORTB value is patched via SMC at note trigger time (row rate).
No ring buffers, no prefetch, no main loop complexity.

**Cost**: 6 cycles × 4 channels = 24 cycles/IRQ (~20% of budget at 15kHz).

**Why this beats ring buffers**:
- Zero failure modes (no buffer underrun at high pitches)
- Zero main RAM cost (no buffers to allocate)
- Minimal code complexity (SMC patch at note trigger, that's all)
- Proven in production (Tebe's player handles 31 Amiga samples across banks)

## Memory Map

```
64KB MODE (current, unchanged):
  $0080-$00BF  Zero page player variables
  $2000-$BFFF  Code + tables + song + samples (linear, ~40KB)
  $C000-$CFFF  OS charset (protected)

EXTENDED MODE:
  $0080-$00BF  Zero page player variables
  $xx00-$3FFF  Player code, IRQ, sequencer, display
  $4000-$7FFF  === BANK WINDOW === (switched via PORTB)
  $8000-$8FFF  VQ codebook + pitch/volume tables (~4KB)
  $9000-$BFFF  Song data + SAMPLE_DIR (~12KB available)
  $C000-$CFFF  OS charset (protected)
```

Key constraint: **VQ codebook (VQ_BLOB) MUST be at $8000+**. The IRQ reads
codebook entries after switching to a sample's bank. Addresses ≥$8000 are
unaffected by PORTB — always main RAM.

## Multi-Bank Samples

Many Amiga MOD samples exceed 16KB. These span consecutive banks:

```
Instrument 3 (22KB):
  Bank 2: $4000-$7FFF (16384 bytes)
  Bank 3: $4000-$5800 (remaining 5616 bytes)
```

The IRQ handles bank crossings in the existing page-boundary path:

```asm
; After incrementing stream pointer high byte:
    inc chN_stream_hi      ; advance to next page
    lda chN_stream_hi
    cmp #$80               ; crossed $7FFF → $8000?
    bcc no_bank_cross
    ; Bank boundary: reset to $40, advance to next bank
    lda #$40
    sta chN_stream_hi
    inc chN_bank_idx       ; next bank in sequence
    ldx chN_bank_idx
    lda SAMPLE_BANK_SEQ,x  ; PORTB value for next bank
    sta chN_bank+1         ; patch SMC
no_bank_cross:
```

This code runs only on page boundaries (every 256 samples = once per ~17ms
at 15kHz). The bank crossing within it happens only every 64 pages (~1.1s).
Cost is negligible.

### SAMPLE_DIR Extensions

```asm
; Existing (64KB):
SAMPLE_START_LO:  .byte <s0, <s1, ...
SAMPLE_START_HI:  .byte >s0, >s1, ...
SAMPLE_END_LO:    .byte <e0, <e1, ...
SAMPLE_END_HI:    .byte >e0, >e1, ...
SAMPLE_MODE:      .byte 0, 1, ...      ; 0=VQ, 1=RAW

; Extended (add these tables):
SAMPLE_PORTB:     .byte $E3, $E3, $C3  ; PORTB for first bank of each sample
SAMPLE_BANK_COUNT:.byte 1, 2, 1        ; how many banks each sample spans
; For multi-bank samples, a sequence table:
SAMPLE_BANK_SEQ:  .byte $E3            ; inst 0: bank 0 only
                  .byte $E3, $C3       ; inst 1: banks 0,1
                  .byte $A3            ; inst 2: bank 2 only
SAMPLE_SEQ_OFF:   .byte 0, 1, 3       ; offset into BANK_SEQ for each inst
```

## XEX Loading Sequence

Bank data is loaded using the standard Atari binary format with INI segments
that switch banks before each data load:

```
Segment 1: copy_os_ram.asm      (INI) — copy OS font to RAM
Segment 2: mem_detect.asm       (INI) — detect banks, store in table
Segment 3: mem_validate.asm     (INI) — check REQUIRED_BANKS, halt if insufficient
Segment 4: bank_switch_0.asm    (INI) — switch to bank 0
Segment 5: ORG $4000, bank 0 sample data
Segment 6: bank_switch_1.asm    (INI) — switch to bank 1
Segment 7: ORG $4000, bank 1 sample data
  ... repeat for each bank ...
Segment N-1: bank_restore.asm   (INI) — LDA #$FF / STA PORTB (main RAM)
Segment N:   Main code + tables + song  (ORG $xx00, ORG $8000)
Segment N+1: RUN start
```

### Memory Detection (INI block)

Uses the dBANK table from MADS @MEM_DETECT. Writes detected PORTB values
to @TAB_MEM_BANKS. Returns count in A.

### Validation (INI block)

```asm
mem_validate:
    lda banks_found
    cmp #REQUIRED_BANKS        ; set by Python builder
    bcs @ok
    ; Display error: "NEED nn BANKS (xxxKB)"
    ;                "FOUND nn BANKS"
    ;                "Song requires extended memory."
    jsr show_mem_error
    jmp *                      ; halt
@ok:
    rts
    ini mem_validate
```

## Bank Packing Algorithm (Python)

First-fit-decreasing bin packing with multi-bank support:

```python
def pack_into_banks(instruments, bank_size=16384):
    """Pack instrument data into 16KB banks.
    
    Large samples span multiple consecutive banks.
    Returns list of banks, each containing placement info.
    """
    # Sort by size descending for better packing
    items = sorted(enumerate(instruments),
                   key=lambda x: x[1].encoded_size, reverse=True)
    
    banks = []  # [{'remaining': int, 'items': [...]}]
    inst_placement = {}  # inst_idx -> {start_bank, offset, n_banks, bank_list}
    
    for inst_idx, inst in items:
        size = inst.encoded_size
        
        if size <= bank_size:
            # Fits in single bank — try first-fit
            placed = False
            for bank_idx, bank in enumerate(banks):
                if bank['remaining'] >= size:
                    offset = bank_size - bank['remaining']
                    inst_placement[inst_idx] = {
                        'start_bank': bank_idx,
                        'offset': 0x4000 + offset,
                        'n_banks': 1,
                        'bank_list': [bank_idx],
                    }
                    bank['remaining'] -= size
                    placed = True
                    break
            if not placed:
                bank_idx = len(banks)
                banks.append({'remaining': bank_size - size})
                inst_placement[inst_idx] = {
                    'start_bank': bank_idx,
                    'offset': 0x4000,
                    'n_banks': 1,
                    'bank_list': [bank_idx],
                }
        else:
            # Multi-bank: needs consecutive empty banks
            n_banks_needed = (size + bank_size - 1) // bank_size
            start_bank = len(banks)  # always append at end (consecutive)
            bank_list = []
            remaining = size
            for i in range(n_banks_needed):
                chunk = min(remaining, bank_size)
                banks.append({'remaining': bank_size - chunk})
                bank_list.append(start_bank + i)
                remaining -= chunk
            inst_placement[inst_idx] = {
                'start_bank': start_bank,
                'offset': 0x4000,
                'n_banks': n_banks_needed,
                'bank_list': bank_list,
            }
    
    return banks, inst_placement
```

## OPTIMIZE Awareness

With banking, the optimizer changes behavior:

| Parameter | 64KB Mode | Extended Mode |
|-----------|-----------|---------------|
| Memory budget | $C000 - code_end | n_banks × 16KB |
| Per-sample limit | total budget | multi-bank allowed |
| IRQ overhead | current | +24 cycles (bank switches) |
| Codebook location | anywhere | must be ≥$8000 |

The optimizer should warn if a sample is so large that even VQ indices exceed
available bank space (unlikely but possible with very long recordings).

## File Organization

```
asm/
  song_player.asm                 ; main — .ifdef USE_BANKING selects path
  tracker/
    tracker_irq_speed.asm         ; 64KB IRQ handler (no banking)
    tracker_irq_banked.asm        ; extended IRQ handler (with banking) — NEW
    parse_event.asm               ; .ifdef adds bank SMC patching
    process_row.asm               ; unchanged
    seq_init.asm                  ; .ifdef adds bank init
  banking/                        ; NEW directory
    mem_detect.asm                ; @MEM_DETECT procedure (from MADS examples)
    mem_validate.asm              ; bank count check + error screen
    bank_switch.asm               ; INI stub template for bank switching
    bank_tables.asm               ; dBANK PORTB values, @TAB_MEM_BANKS
  common/
    copy_os_ram.asm               ; unchanged
    pokey_setup.asm               ; unchanged
```

### Conditional Assembly in song_player.asm

```asm
    icl "SONG_CFG.asm"           ; includes USE_BANKING equate

    .ifdef USE_BANKING
        icl "tracker/tracker_irq_banked.asm"
    .else
        icl "tracker/tracker_irq_speed.asm"
    .endif
```

---

## Implementation Phases

### Phase 1: Foundation (Done)
**Goal**: Solid 64KB mode with configurable start address.

- [x] $C000 boundary check in song_player.asm
- [x] Improved overflow error message with available KB
- [x] Start Address hex input in GUI ($0800–$3F00)
- [x] Memory Config combo in GUI (64KB default, extended options shown)
- [x] Settings persisted in project file

### Phase 2: Bank Packing & Data Generation (Done)
**Goal**: Python side generates banked sample data and extended SAMPLE_DIR.

- [x] `bank_packer.py`: First-fit-decreasing packing (single + multi-bank)
- [x] `bank_packer.py`: generate_bank_asm() — SAMPLE_PORTB, N_BANKS, SEQ tables
- [x] `build.py`: _generate_banking_build() — orchestrates all banking generation
- [x] `build.py`: _generate_bank_data_files() — per-bank .asm with .byte data
- [x] `build.py`: _generate_bank_sample_dir() — absolute $4000+ addresses
- [x] `build.py`: _generate_bank_loader() — multi-segment XEX source
- [x] `build.py`: SONG_CFG.asm emits USE_BANKING=1 and MAX_BANKS=N
- [x] `optimize.py`: Banking budget (n_banks × 16KB) + 24-cycle overhead
- [x] 19 unit tests for bank packer

### Phase 3: Memory Detection & Validation (Done)
**Goal**: XEX boots, detects RAM, validates requirements.

- [x] `asm/banking/mem_detect.asm`: ghost-write detection, dBANK table
- [x] Validation embedded in detect (red screen + halt if insufficient)
- [x] bank_loader.asm generates INI stubs for detect + switch + restore

### Phase 4: Banked IRQ Handler (Done)
**Goal**: IRQ reads sample data from banked memory via PORTB switching.

- [x] `asm/tracker/tracker_irq_banked.asm`: Full 4-channel banked handler
- [x] Bank boundary crossing ($7F→$80) in VQ boundary + RAW boundary paths
- [x] Bank boundary crossing in pitch advance paths (VQ and RAW)
- [x] PORTB restored to $FE at IRQ exit
- [x] `process_row.asm`: .ifdef USE_BANKING for all 4 channels
  - PREPARE: loads SAMPLE_PORTB, SEQ_OFF, N_BANKS per instrument
  - PREPARE: SEI/bank-switch/CLI for first VQ index read from bank
  - COMMIT: patches ch*_bank+1 SMC, sets ch*_bank_seq_idx, ch*_banks_left
- [x] `seq_init.asm`: Banking init (ch*_bank=$FE, seq_idx/banks_left=0)

### Phase 5: Multi-Segment XEX Build (Done)
**Goal**: build.py generates complete multi-segment XEX with bank loading.

- [x] bank_loader.asm: ORG $0600 stubs → ORG $4000 data → song_player.asm
- [x] build_xex_sync: banking branch uses bank_loader.asm as main source
- [x] Per-bank data extraction from VQ_INDICES.asm and RAW_SAMPLES.asm
- [x] Build log shows bank count and utilization

### Phase 6: UI Polish & Integration (Partial — Future)
**Goal**: Smooth user experience with banking awareness throughout.

- [x] Memory config combo enables extended modes
- [x] OPTIMIZE: accounts for banking overhead in suggestions
- [ ] BUILD status: show bank count + utilization in status
- [ ] Instrument list: show bank placement (e.g., "B0", "B0-B1")
- [ ] MOD import: auto-select memory config based on total sample size
- [ ] Test on Altirra with real MODs across all memory configs

---

## Risk Analysis

| Risk | Impact | Mitigation |
|------|--------|------------|
| Bank switch timing | IRQ misses deadline | 24 cycles is known cost; OPTIMIZE accounts for it |
| Multi-bank boundary | Glitch at crossing | Boundary code runs in existing page-wrap path (rare) |
| MADS OPT B+ complexity | Build breaks | Can generate bank data as raw binary, skip MADS banking |
| VQ codebook in wrong address | Garbage audio | Build enforces codebook at $8000+; validation check |
| Sample > total bank space | Can't fit | OPTIMIZE warns; suggest lower rate or VQ |
| Emulator compatibility | Works in Altirra, not others | Test on multiple emulators; Altirra is primary target |

## Testing Strategy

1. **Unit tests** (Python): bank_packer with edge cases (empty, 1 sample, sample = exactly 16KB, sample = 16KB+1, 64 samples)
2. **ASM validation**: assemble with known data sizes, verify no $C000 overflow
3. **Altirra profiles**: test with 64KB, 130XE, 320KB, 1MB configurations
4. **Regression**: all 64KB-mode tests must still pass unchanged
5. **MOD imports**: test with real MODs that have >16KB samples
