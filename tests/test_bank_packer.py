"""Tests for bank_packer module."""
import unittest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bank_packer import (pack_into_banks, generate_bank_asm, 
                          BANK_SIZE, BANK_BASE, DBANK_TABLE, PORTB_MAIN_RAM)


class TestBankPacker(unittest.TestCase):
    """Tests for pack_into_banks."""
    
    def test_empty(self):
        result = pack_into_banks([])
        self.assertTrue(result.success)
        self.assertEqual(result.n_banks_used, 0)
        self.assertEqual(result.total_size, 0)
    
    def test_zero_size_instruments(self):
        result = pack_into_banks([(0, 0), (1, 0), (2, 0)])
        self.assertTrue(result.success)
        self.assertEqual(result.n_banks_used, 0)
    
    def test_single_small_instrument(self):
        result = pack_into_banks([(0, 1000)])
        self.assertTrue(result.success)
        self.assertEqual(result.n_banks_used, 1)
        self.assertEqual(result.total_size, 1000)
        self.assertIn(0, result.placements)
        p = result.placements[0]
        self.assertEqual(p.n_banks, 1)
        self.assertEqual(p.offset, BANK_BASE)  # first in bank = $4000
        self.assertEqual(p.portb_values[0], DBANK_TABLE[0])
    
    def test_two_instruments_fit_one_bank(self):
        result = pack_into_banks([(0, 8000), (1, 8000)])
        self.assertTrue(result.success)
        self.assertEqual(result.n_banks_used, 1)
        self.assertIn(0, result.placements)
        self.assertIn(1, result.placements)
        # Both in same bank
        self.assertEqual(result.placements[0].bank_indices[0],
                         result.placements[1].bank_indices[0])
    
    def test_two_instruments_need_two_banks(self):
        result = pack_into_banks([(0, 10000), (1, 10000)])
        self.assertTrue(result.success)
        self.assertEqual(result.n_banks_used, 2)
        # Different banks
        self.assertNotEqual(result.placements[0].bank_indices[0],
                           result.placements[1].bank_indices[0])
    
    def test_exact_bank_size(self):
        result = pack_into_banks([(0, BANK_SIZE)])
        self.assertTrue(result.success)
        self.assertEqual(result.n_banks_used, 1)
        p = result.placements[0]
        self.assertEqual(p.n_banks, 1)
        self.assertEqual(p.encoded_size, BANK_SIZE)
    
    def test_multi_bank_sample(self):
        """Sample larger than 16KB spans consecutive banks."""
        size = BANK_SIZE + 5000  # 21384 bytes = 2 banks
        result = pack_into_banks([(0, size)])
        self.assertTrue(result.success)
        self.assertEqual(result.n_banks_used, 2)
        p = result.placements[0]
        self.assertEqual(p.n_banks, 2)
        self.assertEqual(len(p.bank_indices), 2)
        self.assertEqual(p.bank_indices[0], 0)
        self.assertEqual(p.bank_indices[1], 1)
        self.assertEqual(len(p.portb_values), 2)
    
    def test_multi_bank_three_banks(self):
        """Sample spanning exactly 3 banks."""
        size = BANK_SIZE * 2 + 100
        result = pack_into_banks([(0, size)])
        self.assertTrue(result.success)
        self.assertEqual(result.n_banks_used, 3)
        p = result.placements[0]
        self.assertEqual(p.n_banks, 3)
    
    def test_max_banks_exceeded(self):
        """Error when needing more banks than available."""
        # 5 instruments × 16KB = need 5 banks, only allow 4
        items = [(i, BANK_SIZE) for i in range(5)]
        result = pack_into_banks(items, max_banks=4)
        self.assertFalse(result.success)
        self.assertTrue(len(result.error) > 0)
    
    def test_multi_bank_exceeds_limit(self):
        """Error when one multi-bank sample needs more consecutive banks than available."""
        size = BANK_SIZE * 5 + 1  # needs 6 banks
        result = pack_into_banks([(0, size)], max_banks=4)
        self.assertFalse(result.success)
    
    def test_first_fit_decreasing_packing(self):
        """Large items placed first for better packing."""
        # 12KB + 12KB + 4KB + 4KB = 32KB = exactly 2 banks
        items = [(0, 4000), (1, 12000), (2, 4000), (3, 12000)]
        result = pack_into_banks(items)
        self.assertTrue(result.success)
        self.assertEqual(result.n_banks_used, 2)
    
    def test_mixed_single_and_multi(self):
        """Mix of single-bank and multi-bank samples."""
        items = [
            (0, BANK_SIZE + 100),  # multi: 2 banks
            (1, 5000),             # single: fits in remaining of bank 1
            (2, 1000),             # single: fits somewhere
        ]
        result = pack_into_banks(items)
        self.assertTrue(result.success)
        self.assertEqual(result.placements[0].n_banks, 2)
        self.assertEqual(result.placements[1].n_banks, 1)
        self.assertEqual(result.placements[2].n_banks, 1)
    
    def test_portb_values_correct(self):
        """PORTB values match dBANK table."""
        items = [(0, BANK_SIZE), (1, BANK_SIZE), (2, BANK_SIZE)]
        result = pack_into_banks(items)
        self.assertTrue(result.success)
        for inst_idx, p in result.placements.items():
            for bi, portb in zip(p.bank_indices, p.portb_values):
                self.assertEqual(portb, DBANK_TABLE[bi])
    
    def test_bank_seq_table(self):
        """bank_seq contains flattened PORTB values."""
        items = [
            (0, BANK_SIZE + 100),  # 2 banks
            (1, 5000),             # 1 bank
        ]
        result = pack_into_banks(items)
        self.assertTrue(result.success)
        self.assertTrue(len(result.bank_seq) >= 3)  # 2 + 1
    
    def test_utilization(self):
        """Bank utilization reported correctly."""
        result = pack_into_banks([(0, BANK_SIZE // 2)])  # half a bank
        self.assertTrue(result.success)
        self.assertEqual(len(result.bank_utilization), 1)
        self.assertAlmostEqual(result.bank_utilization[0], 0.5, places=2)
    
    def test_130xe_banks(self):
        """4-bank 130XE configuration."""
        # 8 instruments × 8KB = 64KB, fits in 4 banks (2 per bank)
        items = [(i, 8000) for i in range(8)]
        result = pack_into_banks(items, max_banks=4)
        self.assertTrue(result.success)
        self.assertLessEqual(result.n_banks_used, 4)


class TestGenerateBankAsm(unittest.TestCase):
    """Tests for ASM table generation."""
    
    def test_generates_tables(self):
        result = pack_into_banks([(0, 1000), (1, 2000)])
        asm = generate_bank_asm(result, 4)
        self.assertIn("REQUIRED_BANKS", asm)
        self.assertIn("SAMPLE_PORTB", asm)
        self.assertIn("SAMPLE_N_BANKS", asm)
        self.assertIn("SAMPLE_BANK_SEQ_OFF", asm)
        self.assertIn("SAMPLE_BANK_SEQ", asm)
    
    def test_unused_instruments_get_main_ram(self):
        result = pack_into_banks([(1, 1000)])  # only inst 1
        asm = generate_bank_asm(result, 3)  # 3 total instruments
        # Inst 0 and 2 should have $FE (main RAM)
        self.assertIn(f"${PORTB_MAIN_RAM:02X}", asm)
    
    def test_multi_bank_n_banks(self):
        result = pack_into_banks([(0, BANK_SIZE + 100)])
        asm = generate_bank_asm(result, 1)
        self.assertIn("SAMPLE_N_BANKS", asm)
        # Should contain "2" for the multi-bank sample
        lines = asm.split('\n')
        nbanks_idx = next(i for i, l in enumerate(lines) if 'SAMPLE_N_BANKS' in l)
        nbanks_line = lines[nbanks_idx + 1]
        self.assertIn("2", nbanks_line)


class TestPageAlignment(unittest.TestCase):
    """Tests for page-aligned bank placement (RAW safety fix)."""
    
    def test_second_item_page_aligned(self):
        """Second item in shared bank must be page-aligned."""
        r = pack_into_banks([(0, 300), (1, 200)])
        self.assertEqual(r.n_banks_used, 1)
        p1 = r.placements[1]
        self.assertEqual(p1.offset % 256, 0,
                        f"Inst 1 not page-aligned: ${p1.offset:04X}")
    
    def test_page_alignment_waste_tracked(self):
        """Page alignment waste doesn't overflow bank."""
        # 300 bytes + 200 bytes + alignment = should still fit in 1 bank
        r = pack_into_banks([(0, 300), (1, 200)])
        self.assertEqual(r.n_banks_used, 1)
        # Second item at next page boundary after first
        p0 = r.placements[0]
        p1 = r.placements[1]
        self.assertGreaterEqual(p1.offset, p0.offset + p0.encoded_size)
    
    def test_first_item_always_page_aligned(self):
        """First item in a new bank starts at $4000 (page-aligned)."""
        r = pack_into_banks([(0, 500)])
        self.assertEqual(r.placements[0].offset, BANK_BASE)
    
    def test_alignment_forces_new_bank(self):
        """When alignment waste pushes item to next bank."""
        # Nearly-full bank: BANK_SIZE - 1 bytes, then 256 byte item
        r = pack_into_banks([(0, BANK_SIZE - 1), (1, 256)])
        # Item 0 fills bank 0 almost entirely
        # Item 1 needs page alignment after item 0, no room → new bank
        self.assertEqual(r.n_banks_used, 2)


class TestSeqOffsetField(unittest.TestCase):
    """Test that seq_offset is a proper dataclass field."""
    
    def test_seq_offset_initialized(self):
        """seq_offset should default to 0."""
        from bank_packer import InstrumentPlacement
        p = InstrumentPlacement(inst_idx=0, start_bank=0, offset=0x4000,
                               encoded_size=100, n_banks=1, bank_indices=[0],
                               portb_values=[0xE3])
        self.assertEqual(p.seq_offset, 0)
    
    def test_seq_offset_populated(self):
        """pack_into_banks sets seq_offset for each instrument."""
        r = pack_into_banks([(0, 500), (1, 300)])
        for idx, p in r.placements.items():
            self.assertIsInstance(p.seq_offset, int)


class TestEndAddressBoundary(unittest.TestCase):
    """Test end address for samples that fill a bank exactly."""
    
    def test_exact_bank_fill(self):
        """Sample filling exact bank size: end should be BANK_BASE + BANK_SIZE."""
        r = pack_into_banks([(0, BANK_SIZE)])
        p = r.placements[0]
        end = (p.end_addr_hi << 8) | p.end_addr_lo
        self.assertEqual(end, BANK_BASE + BANK_SIZE)
    
    def test_multi_bank_last_bank_end(self):
        """Multi-bank: end address in last bank."""
        extra = 1000
        r = pack_into_banks([(0, BANK_SIZE + extra)])
        p = r.placements[0]
        end = (p.end_addr_hi << 8) | p.end_addr_lo
        self.assertEqual(end, BANK_BASE + extra)


class TestRawLabelExtraction(unittest.TestCase):
    """Test _extract_raw_blocks with both label conventions."""
    
    def test_new_label_format(self):
        """RAW_INST_NN format (converter output)."""
        import tempfile, os
        content = (
            "; RAW sample\n"
            "    .align $100\n"
            "RAW_INST_00\n"
            " .byte $0A,$0B,$0C\n"
            "RAW_INST_00_END\n"
        )
        with tempfile.NamedTemporaryFile(mode='w', suffix='.asm', 
                                          delete=False) as f:
            f.write(content)
            path = f.name
        try:
            from build import _extract_raw_blocks
            blocks = _extract_raw_blocks(path)
            self.assertIn(0, blocks)
            self.assertEqual(list(blocks[0]), [0x0A, 0x0B, 0x0C])
        finally:
            os.unlink(path)
    
    def test_old_label_format(self):
        """RAW_SAMPLES_N format (backward compat)."""
        import tempfile, os
        content = (
            "RAW_SAMPLES_3\n"
            " .byte $FF,$FE\n"
            "RAW_SAMPLES_3_END\n"
        )
        with tempfile.NamedTemporaryFile(mode='w', suffix='.asm',
                                          delete=False) as f:
            f.write(content)
            path = f.name
        try:
            from build import _extract_raw_blocks
            blocks = _extract_raw_blocks(path)
            self.assertIn(3, blocks)
            self.assertEqual(list(blocks[3]), [0xFF, 0xFE])
        finally:
            os.unlink(path)


if __name__ == '__main__':
    unittest.main()
