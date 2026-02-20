"""Bank Packer — Packs instrument sample data into 16KB memory banks.

For Atari XL/XE extended memory ($4000-$7FFF bank window).
Supports multi-bank samples that span consecutive banks.

The DBANK_TABLE PORTB values are grouped by 64KB block, 4 banks per block.
Blocks are probed highest-first (X=15→0) for SpartaDOS X compatibility.
Within each block, bits 2,3 of PORTB select one of 4 physical banks.

On a 130XE (4 banks): only Block 15 has physical RAM → banks 0-3.
On 320k RAMBO (16 banks): Blocks 15-12 → banks 0-15.
On 1088k RAMBO (64 banks): all 16 blocks → banks 0-63.

This ordering matches the alias-aware runtime detection in mem_detect.asm
and ensures that entries 0..N-1 always address N distinct physical banks,
regardless of which memory expansion is installed.
"""

import logging
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

BANK_SIZE = 16384  # 16KB per bank ($4000-$7FFF)
BANK_BASE = 0x4000  # Start of bank window

# PORTB values for banking, grouped by 64KB block (4 banks per block).
# Block detection order: X=15 downto 0 (highest-first for SDX compat).
# Within each block, bits 2,3 cycle through 00,01,10,11.
# Bit 4 = 0 (CPU bank enable), Bit 0 = 1 (OS ROM on during loading).
#
# 130XE (4 banks):  uses entries 0-3  (Block 15)
# 192k  (8 banks):  uses entries 0-7  (Blocks 15-14)
# 320k  (16 banks): uses entries 0-15 (Blocks 15-12)
# 576k  (32 banks): uses entries 0-31 (Blocks 15-8)
# 1088k (64 banks): uses entries 0-63 (all blocks)
DBANK_TABLE = [
    # Block 15 (X=%1111, bits 7,6,5,1=1,1,1,1):  banks 0-3
    0xE3, 0xE7, 0xEB, 0xEF,
    # Block 14 (X=%1110, bits 7,6,5,1=1,1,0,1):  banks 4-7
    0xC3, 0xC7, 0xCB, 0xCF,
    # Block 13 (X=%1101, bits 7,6,5,1=1,0,1,1):  banks 8-11
    0xA3, 0xA7, 0xAB, 0xAF,
    # Block 12 (X=%1100, bits 7,6,5,1=1,0,0,1):  banks 12-15
    0x83, 0x87, 0x8B, 0x8F,
    # Block 11 (X=%1011, bits 7,6,5,1=0,1,1,1):  banks 16-19
    0x63, 0x67, 0x6B, 0x6F,
    # Block 10 (X=%1010, bits 7,6,5,1=0,1,0,1):  banks 20-23
    0x43, 0x47, 0x4B, 0x4F,
    # Block  9 (X=%1001, bits 7,6,5,1=0,0,1,1):  banks 24-27
    0x23, 0x27, 0x2B, 0x2F,
    # Block  8 (X=%1000, bits 7,6,5,1=0,0,0,1):  banks 28-31
    0x03, 0x07, 0x0B, 0x0F,
    # Block  7 (X=%0111, bits 7,6,5,1=1,1,1,0):  banks 32-35
    0xE1, 0xE5, 0xE9, 0xED,
    # Block  6 (X=%0110, bits 7,6,5,1=1,1,0,0):  banks 36-39
    0xC1, 0xC5, 0xC9, 0xCD,
    # Block  5 (X=%0101, bits 7,6,5,1=1,0,1,0):  banks 40-43
    0xA1, 0xA5, 0xA9, 0xAD,
    # Block  4 (X=%0100, bits 7,6,5,1=1,0,0,0):  banks 44-47
    0x81, 0x85, 0x89, 0x8D,
    # Block  3 (X=%0011, bits 7,6,5,1=0,1,1,0):  banks 48-51
    0x61, 0x65, 0x69, 0x6D,
    # Block  2 (X=%0010, bits 7,6,5,1=0,1,0,0):  banks 52-55
    0x41, 0x45, 0x49, 0x4D,
    # Block  1 (X=%0001, bits 7,6,5,1=0,0,1,0):  banks 56-59
    0x21, 0x25, 0x29, 0x2D,
    # Block  0 (X=%0000, bits 7,6,5,1=0,0,0,0):  banks 60-63
    0x01, 0x05, 0x09, 0x0D,
]

PORTB_MAIN_RAM = 0xFE  # PORTB value for main RAM (no banking)


@dataclass
class InstrumentPlacement:
    """Placement of one instrument in bank(s)."""
    inst_idx: int
    start_bank: int           # First bank index
    offset: int               # Start address within first bank ($4000+offset)
    encoded_size: int          # Total encoded size in bytes
    n_banks: int              # Number of banks spanned
    bank_indices: List[int] = field(default_factory=list)  # Bank indices used
    portb_values: List[int] = field(default_factory=list)  # PORTB per bank
    # For end-of-sample detection
    end_addr_hi: int = 0      # High byte of end address in last bank
    end_addr_lo: int = 0      # Low byte of end address in last bank
    seq_offset: int = 0       # Offset into SAMPLE_BANK_SEQ table


@dataclass
class BankPackResult:
    """Result of packing instruments into banks."""
    n_banks_used: int = 0
    max_banks_available: int = 0
    placements: Dict[int, InstrumentPlacement] = field(default_factory=dict)
    bank_utilization: List[float] = field(default_factory=list)  # 0.0-1.0 per bank
    bank_has_codebook: List[bool] = field(default_factory=list)  # per bank
    bank_seq: List[int] = field(default_factory=list)  # Flat PORTB sequence
    total_size: int = 0
    error: str = ""

    @property
    def success(self) -> bool:
        return self.error == ""


def pack_into_banks(inst_sizes: List[Tuple[int, int]],
                    max_banks: int = 64,
                    codebook_size: int = 0,
                    vq_instruments: Optional[set] = None) -> BankPackResult:
    """Pack instrument data into 16KB banks.
    
    Two-phase packing when vq_instruments is provided:
      Phase 1: VQ instruments → banks WITH codebook (effective = 16KB - codebook)
      Phase 2: RAW instruments → banks WITHOUT codebook (effective = 16KB)
    This avoids wasting codebook space in RAW-only banks.
    
    Args:
        inst_sizes: List of (inst_idx, encoded_size_bytes).
                    Instruments with size 0 are skipped.
        max_banks: Maximum number of banks available.
        codebook_size: Bytes reserved at start of each VQ bank for per-bank
                       codebook (e.g. 256*vec_size=2048 for vec_size=8).
                       Pass 0 for no codebook.
        vq_instruments: Set of instrument indices that are VQ-encoded.
                        If None or empty, all instruments treated as RAW
                        (no codebook overhead in any bank).
    
    Returns:
        BankPackResult with placement info for each instrument.
    """
    result = BankPackResult(max_banks_available=max_banks)
    
    if not inst_sizes:
        return result
    
    # Filter out zero-size instruments
    active = [(idx, sz) for idx, sz in inst_sizes if sz > 0]
    if not active:
        return result
    
    result.total_size = sum(sz for _, sz in active)
    
    if vq_instruments is None:
        vq_instruments = set()
    
    # Split into VQ and RAW
    vq_items = [(idx, sz) for idx, sz in active if idx in vq_instruments]
    raw_items = [(idx, sz) for idx, sz in active if idx not in vq_instruments]
    
    # Effective capacities
    vq_bank_size = BANK_SIZE - codebook_size if codebook_size > 0 else BANK_SIZE
    raw_bank_size = BANK_SIZE
    
    if vq_bank_size <= 0:
        result.error = f"Codebook size ({codebook_size}) >= bank size ({BANK_SIZE})"
        return result
    
    # Quick capacity check (optimistic — no alignment waste)
    vq_total = sum(sz for _, sz in vq_items)
    raw_total = sum(sz for _, sz in raw_items)
    vq_banks_min = (vq_total + vq_bank_size - 1) // vq_bank_size if vq_total > 0 else 0
    raw_banks_min = (raw_total + raw_bank_size - 1) // raw_bank_size if raw_total > 0 else 0
    if vq_banks_min + raw_banks_min > max_banks:
        result.error = (f"Total sample data ({result.total_size // 1024}KB) "
                       f"exceeds {max_banks} banks "
                       f"(~{vq_banks_min * vq_bank_size // 1024}KB VQ + "
                       f"~{raw_banks_min * raw_bank_size // 1024}KB RAW capacity)")
        return result
    
    # Phase 1: Pack VQ instruments (with codebook overhead)
    # Sort by size descending (first-fit-decreasing)
    vq_sorted = sorted(vq_items, key=lambda x: x[1], reverse=True)
    banks = []  # [(remaining_bytes, next_free_offset, has_codebook)]
    
    for inst_idx, size in vq_sorted:
        if not _do_pack_item(result, inst_idx, size, banks, max_banks,
                             vq_bank_size, codebook_size, is_vq=True):
            return result
    
    # Phase 2: Pack RAW instruments (no codebook overhead)
    raw_sorted = sorted(raw_items, key=lambda x: x[1], reverse=True)
    
    for inst_idx, size in raw_sorted:
        if not _do_pack_item(result, inst_idx, size, banks, max_banks,
                             raw_bank_size, 0, is_vq=False):
            return result
    
    # Compute utilization and bank metadata
    result.n_banks_used = len(banks)
    result.bank_utilization = [
        1.0 - (remaining / BANK_SIZE) for remaining, _, _ in banks
    ]
    result.bank_has_codebook = [has_cb for _, _, has_cb in banks]
    
    # Build flat PORTB sequence table
    _build_bank_seq(result)
    
    logger.info(f"Packed {len(result.placements)} instruments into "
                f"{result.n_banks_used} banks "
                f"({result.total_size // 1024}KB total, "
                f"{sum(result.bank_has_codebook)} VQ banks, "
                f"{result.n_banks_used - sum(result.bank_has_codebook)} RAW banks)")
    
    return result


def _do_pack_item(result, inst_idx, size, banks, max_banks,
                  effective_bank_size, codebook_offset, is_vq):
    """Pack one instrument. Returns True on success, False on failure (sets result.error)."""
    n_banks_needed = (size + effective_bank_size - 1) // effective_bank_size
    
    if n_banks_needed == 1:
        # Single-bank: first-fit with page alignment (only in same-type banks)
        placed = False
        for bank_idx, (remaining, offset, has_cb) in enumerate(banks):
            # Only place VQ in VQ banks, RAW in RAW banks
            if has_cb != is_vq:
                continue
            aligned_offset = (offset + 255) & ~255
            waste = aligned_offset - offset
            if remaining >= size + waste:
                _place_single(result, inst_idx, size, bank_idx,
                              aligned_offset, codebook_offset)
                banks[bank_idx] = (remaining - size - waste,
                                   aligned_offset + size, has_cb)
                placed = True
                break
        
        if not placed:
            bank_idx = len(banks)
            if bank_idx >= max_banks:
                result.error = (f"Need more than {max_banks} banks. "
                               f"Reduce samples or use VQ compression.")
                return False
            banks.append((effective_bank_size - size, size, is_vq))
            _place_single(result, inst_idx, size, bank_idx, 0,
                          codebook_offset)
    else:
        # Multi-bank: consecutive new banks
        start_bank = len(banks)
        if start_bank + n_banks_needed > max_banks:
            result.error = (f"Instrument {inst_idx} ({size // 1024}KB) needs "
                           f"{n_banks_needed} consecutive banks, "
                           f"only {max_banks - start_bank} available.")
            return False
        
        bank_indices = []
        remaining_size = size
        for i in range(n_banks_needed):
            chunk = min(remaining_size, effective_bank_size)
            banks.append((effective_bank_size - chunk, chunk, is_vq))
            bank_indices.append(start_bank + i)
            remaining_size -= chunk
        
        _place_multi(result, inst_idx, size, bank_indices, codebook_offset)
    
    return True


def _place_single(result: BankPackResult, inst_idx: int, size: int,
                  bank_idx: int, offset: int, codebook_size: int = 0):
    """Place a single-bank instrument."""
    # offset is relative to data area start (after codebook)
    addr = BANK_BASE + codebook_size + offset
    end_addr = addr + size
    
    # Runtime PORTB: bit 0=0 (OS ROM disabled) so RAM-under-ROM stays visible
    portb = (DBANK_TABLE[bank_idx] & 0xFE) if bank_idx < len(DBANK_TABLE) else 0xFE
    
    result.placements[inst_idx] = InstrumentPlacement(
        inst_idx=inst_idx,
        start_bank=bank_idx,
        offset=addr,
        encoded_size=size,
        n_banks=1,
        bank_indices=[bank_idx],
        portb_values=[portb],
        end_addr_hi=(end_addr >> 8) & 0xFF,
        end_addr_lo=end_addr & 0xFF,
    )


def _place_multi(result: BankPackResult, inst_idx: int, size: int,
                 bank_indices: List[int], codebook_size: int = 0):
    """Place a multi-bank instrument across consecutive banks."""
    portb_values = []
    for bi in bank_indices:
        # Runtime PORTB: bit 0=0 (OS ROM disabled)
        portb = (DBANK_TABLE[bi] & 0xFE) if bi < len(DBANK_TABLE) else 0xFE
        portb_values.append(portb)
    
    # Data starts after codebook in each bank
    data_base = BANK_BASE + codebook_size
    effective_bank_size = BANK_SIZE - codebook_size
    
    # End address: how much is used in the last bank
    last_bank_used = size - (len(bank_indices) - 1) * effective_bank_size
    end_addr = data_base + last_bank_used
    
    result.placements[inst_idx] = InstrumentPlacement(
        inst_idx=inst_idx,
        start_bank=bank_indices[0],
        offset=data_base,  # Multi-bank always starts at data_base
        encoded_size=size,
        n_banks=len(bank_indices),
        bank_indices=bank_indices,
        portb_values=portb_values,
        end_addr_hi=(end_addr >> 8) & 0xFF,
        end_addr_lo=end_addr & 0xFF,
    )


def _build_bank_seq(result: BankPackResult):
    """Build the flat SAMPLE_BANK_SEQ table and per-instrument offsets."""
    seq = []
    for inst_idx in sorted(result.placements.keys()):
        p = result.placements[inst_idx]
        p.seq_offset = len(seq)  # Store offset for ASM generation
        seq.extend(p.portb_values)
    result.bank_seq = seq


def generate_bank_asm(result: BankPackResult, n_instruments: int,
                      codebook_bytes: int = 0,
                      vq_instruments: Optional[set] = None) -> str:
    """Generate BANK_CFG.asm with all banking tables.
    
    Args:
        result: BankPackResult from pack_into_banks
        n_instruments: Total number of instruments (including unused)
        codebook_bytes: Per-bank codebook size in bytes for VQ banks
        vq_instruments: Set of VQ instrument indices
    
    Returns:
        ASM source string
    """
    if vq_instruments is None:
        vq_instruments = set()
    
    lines = []
    lines.append("; ==========================================================================")
    lines.append("; BANK_CFG.asm - Extended Memory Banking Configuration")
    lines.append("; ==========================================================================")
    lines.append("; Generated by POKEY VQ Tracker bank packer")
    lines.append("; ==========================================================================")
    lines.append("")
    lines.append(".ifndef REQUIRED_BANKS")
    lines.append(f"REQUIRED_BANKS = {result.n_banks_used}")
    lines.append(".endif")
    lines.append("")
    
    # Note: BANK_CODEBOOK_BYTES is defined in VQ_CFG.asm (included earlier).
    # Do NOT redefine it here — MADS errors on duplicate symbol definitions.
    
    # SAMPLE_DATA_HI: hi byte of data start address per instrument
    # VQ instruments: data starts after codebook ($4000 + codebook_bytes)
    # RAW instruments: data starts at $4000
    data_hi_vals = []
    vq_data_hi = (BANK_BASE + codebook_bytes) >> 8 if codebook_bytes > 0 else BANK_BASE >> 8
    raw_data_hi = BANK_BASE >> 8  # $40
    for i in range(n_instruments):
        if i in vq_instruments:
            data_hi_vals.append(f"${vq_data_hi:02X}")
        else:
            data_hi_vals.append(f"${raw_data_hi:02X}")
    lines.append("; Hi byte of data start in bank (per instrument)")
    lines.append("; VQ instruments: after codebook. RAW: bank start ($40).")
    lines.append("SAMPLE_DATA_HI:")
    lines.append(f"    .byte {','.join(data_hi_vals)}")
    lines.append("")
    
    # SAMPLE_PORTB: first bank's PORTB value per instrument
    portb_vals = []
    for i in range(n_instruments):
        if i in result.placements:
            portb_vals.append(f"${result.placements[i].portb_values[0]:02X}")
        else:
            portb_vals.append(f"${PORTB_MAIN_RAM:02X}")
    lines.append("; PORTB value for each instrument's first bank")
    lines.append("SAMPLE_PORTB:")
    lines.append(f"    .byte {','.join(portb_vals)}")
    lines.append("")
    
    # SAMPLE_N_BANKS: number of banks per instrument
    nbanks = []
    for i in range(n_instruments):
        if i in result.placements:
            nbanks.append(str(result.placements[i].n_banks))
        else:
            nbanks.append("1")
    lines.append("; Number of banks each instrument spans")
    lines.append("SAMPLE_N_BANKS:")
    lines.append(f"    .byte {','.join(nbanks)}")
    lines.append("")
    
    # SAMPLE_BANK_SEQ_OFF: offset into BANK_SEQ table per instrument
    offsets = []
    for i in range(n_instruments):
        if i in result.placements:
            offsets.append(str(result.placements[i].seq_offset))
        else:
            offsets.append("0")
    lines.append("; Offset into SAMPLE_BANK_SEQ for each instrument")
    lines.append("SAMPLE_BANK_SEQ_OFF:")
    lines.append(f"    .byte {','.join(offsets)}")
    lines.append("")
    
    # SAMPLE_BANK_SEQ: flat sequence of PORTB values
    if result.bank_seq:
        seq_vals = [f"${v:02X}" for v in result.bank_seq]
        lines.append("; Packed PORTB values (multi-bank instruments span consecutive entries)")
        lines.append("SAMPLE_BANK_SEQ:")
        # Split long lines
        for i in range(0, len(seq_vals), 16):
            chunk = seq_vals[i:i+16]
            lines.append(f"    .byte {','.join(chunk)}")
    else:
        lines.append("SAMPLE_BANK_SEQ:")
        lines.append(f"    .byte ${PORTB_MAIN_RAM:02X}")
    lines.append("")
    
    return '\n'.join(lines)



