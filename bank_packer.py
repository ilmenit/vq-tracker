"""Bank Packer — Packs instrument sample data into 16KB memory banks.

For Atari XL/XE extended memory ($4000-$7FFF bank window).
Supports multi-bank samples that span consecutive banks.

The dBANK PORTB value table follows the MADS @MEM_DETECT ordering,
matching the Atari hardware banking scheme.
"""

import logging
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

BANK_SIZE = 16384  # 16KB per bank ($4000-$7FFF)
BANK_BASE = 0x4000  # Start of bank window

# PORTB values for banking, ordered as in MADS @MEM_DETECT dBANK table.
# 64 entries covering up to 1MB extended memory.
# Bank 0 = first entry, Bank 1 = second, etc.
DBANK_TABLE = [
    0xE3, 0xC3, 0xA3, 0x83, 0x63, 0x43, 0x23, 0x03,
    0xE7, 0xC7, 0xA7, 0x87, 0x67, 0x47, 0x27, 0x07,
    0xEB, 0xCB, 0xAB, 0x8B, 0x6B, 0x4B, 0x2B, 0x0B,
    0xEF, 0xCF, 0xAF, 0x8F, 0x6F, 0x4F, 0x2F, 0x0F,
    0xED, 0xCD, 0xAD, 0x8D, 0x6D, 0x4D, 0x2D, 0x0D,
    0xE9, 0xC9, 0xA9, 0x89, 0x69, 0x49, 0x29, 0x09,
    0xE5, 0xC5, 0xA5, 0x85, 0x65, 0x45, 0x25, 0x05,
    0xE1, 0xC1, 0xA1, 0x81, 0x61, 0x41, 0x21, 0x01,
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
    bank_seq: List[int] = field(default_factory=list)  # Flat PORTB sequence
    total_size: int = 0
    error: str = ""

    @property
    def success(self) -> bool:
        return self.error == ""


def pack_into_banks(inst_sizes: List[Tuple[int, int]],
                    max_banks: int = 64) -> BankPackResult:
    """Pack instrument data into 16KB banks.
    
    Args:
        inst_sizes: List of (inst_idx, encoded_size_bytes).
                    Instruments with size 0 are skipped.
        max_banks: Maximum number of banks available.
    
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
    
    # Check if total fits at all
    total_capacity = max_banks * BANK_SIZE
    if result.total_size > total_capacity:
        result.error = (f"Total sample data ({result.total_size // 1024}KB) "
                       f"exceeds {max_banks} banks ({total_capacity // 1024}KB)")
        return result
    
    # Sort by size descending (first-fit-decreasing)
    sorted_items = sorted(active, key=lambda x: x[1], reverse=True)
    
    # Bank tracking: list of remaining space per bank
    banks = []  # [(remaining_bytes, next_free_offset)]
    
    for inst_idx, size in sorted_items:
        if size <= 0:
            continue
        
        n_banks_needed = (size + BANK_SIZE - 1) // BANK_SIZE
        
        if n_banks_needed == 1:
            # Single-bank: try first-fit with page alignment
            # Page alignment ensures RAW samples don't cross $8000
            # boundary within a page (last page would read from main RAM)
            placed = False
            for bank_idx, (remaining, offset) in enumerate(banks):
                aligned_offset = (offset + 255) & ~255  # round up to 256
                waste = aligned_offset - offset
                if remaining >= size + waste:
                    _place_single(result, inst_idx, size, bank_idx, aligned_offset)
                    banks[bank_idx] = (remaining - size - waste, aligned_offset + size)
                    placed = True
                    break
            
            if not placed:
                # Need a new bank (offset 0 is already page-aligned)
                bank_idx = len(banks)
                if bank_idx >= max_banks:
                    result.error = (f"Need more than {max_banks} banks. "
                                   f"Reduce samples or use VQ compression.")
                    return result
                banks.append((BANK_SIZE - size, size))
                _place_single(result, inst_idx, size, bank_idx, 0)
        else:
            # Multi-bank: always allocate consecutive new banks
            start_bank = len(banks)
            if start_bank + n_banks_needed > max_banks:
                result.error = (f"Instrument {inst_idx} ({size // 1024}KB) needs "
                               f"{n_banks_needed} consecutive banks, "
                               f"only {max_banks - start_bank} available.")
                return result
            
            # Allocate consecutive banks
            bank_indices = []
            remaining_size = size
            for i in range(n_banks_needed):
                chunk = min(remaining_size, BANK_SIZE)
                banks.append((BANK_SIZE - chunk, chunk))
                bank_indices.append(start_bank + i)
                remaining_size -= chunk
            
            _place_multi(result, inst_idx, size, bank_indices)
    
    # Compute utilization
    result.n_banks_used = len(banks)
    result.bank_utilization = [
        1.0 - (remaining / BANK_SIZE) for remaining, _ in banks
    ]
    
    # Build flat PORTB sequence table
    _build_bank_seq(result)
    
    logger.info(f"Packed {len(result.placements)} instruments into "
                f"{result.n_banks_used} banks "
                f"({result.total_size // 1024}KB total)")
    
    return result


def _place_single(result: BankPackResult, inst_idx: int, size: int,
                  bank_idx: int, offset: int):
    """Place a single-bank instrument."""
    addr = BANK_BASE + offset
    end_addr = addr + size
    
    portb = DBANK_TABLE[bank_idx] if bank_idx < len(DBANK_TABLE) else 0xFF
    
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
                 bank_indices: List[int]):
    """Place a multi-bank instrument across consecutive banks."""
    portb_values = []
    for bi in bank_indices:
        portb = DBANK_TABLE[bi] if bi < len(DBANK_TABLE) else 0xFF
        portb_values.append(portb)
    
    # End address: how much is used in the last bank
    last_bank_used = size - (len(bank_indices) - 1) * BANK_SIZE
    end_addr = BANK_BASE + last_bank_used
    
    result.placements[inst_idx] = InstrumentPlacement(
        inst_idx=inst_idx,
        start_bank=bank_indices[0],
        offset=BANK_BASE,  # Multi-bank always starts at $4000
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


def generate_bank_asm(result: BankPackResult, n_instruments: int) -> str:
    """Generate BANK_CFG.asm with all banking tables.
    
    Args:
        result: BankPackResult from pack_into_banks
        n_instruments: Total number of instruments (including unused)
    
    Returns:
        ASM source string
    """
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


def generate_bank_load_stubs(result: BankPackResult) -> List[Tuple[int, str]]:
    """Generate INI stub ASM for each bank load.
    
    Returns list of (bank_idx, asm_source) tuples.
    Each stub switches PORTB to the target bank.
    """
    stubs = []
    for bank_idx in range(result.n_banks_used):
        portb = DBANK_TABLE[bank_idx] if bank_idx < len(DBANK_TABLE) else 0xFF
        asm = (
            f"; Switch to bank {bank_idx} for loading\n"
            f"    org $2000\n"  # Temp location for INI code
            f"switch_bank_{bank_idx}:\n"
            f"    lda #${portb:02X}\n"
            f"    sta $D301\n"  # PORTB direct
            f"    rts\n"
            f"    ini switch_bank_{bank_idx}\n"
        )
        stubs.append((bank_idx, asm))
    return stubs
