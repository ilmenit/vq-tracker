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
        self.assertEqual(p.portb_values[0], DBANK_TABLE[0] & 0xFE)
    
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
        """PORTB values match dBANK table with bit 0 cleared (OS ROM off)."""
        items = [(0, BANK_SIZE), (1, BANK_SIZE), (2, BANK_SIZE)]
        result = pack_into_banks(items)
        self.assertTrue(result.success)
        for inst_idx, p in result.placements.items():
            for bi, portb in zip(p.bank_indices, p.portb_values):
                self.assertEqual(portb, DBANK_TABLE[bi] & 0xFE)
    
    def test_bank_seq_table(self):
        """bank_seq contains flattened PORTB values."""
        items = [
            (0, BANK_SIZE + 100),  # 2 banks
            (1, 5000),             # 1 bank
        ]
        result = pack_into_banks(items)
        self.assertTrue(result.success)
        self.assertTrue(len(result.bank_seq) >= 3)  # 2 + 1
    
    def test_portb_bit0_cleared_for_runtime(self):
        """All runtime PORTB values must have bit 0=0 (OS ROM disabled).
        
        PORTB bit 0 controls the OS ROM overlay at $C000-$CFFF and $D800-$FFFF.
        During XEX loading, bit 0=1 (OS visible) is correct.
        During playback, bit 0=0 (OS hidden) is required so that RAM data
        at $C000+ remains accessible. Regression test for the bit 0 fix.
        """
        # Test single-bank, multi-bank, and full packing
        items = [(0, 8000), (1, 20000), (2, 4000)]  # mix of sizes
        result = pack_into_banks(items)
        self.assertTrue(result.success)
        # Check all placement PORTB values
        for inst_idx, p in result.placements.items():
            for portb in p.portb_values:
                self.assertEqual(portb & 1, 0,
                    f"Inst {inst_idx}: PORTB ${portb:02X} has bit 0=1 (OS ROM ON)")
        # Check bank_seq (runtime lookup table)
        for i, portb in enumerate(result.bank_seq):
            self.assertEqual(portb & 1, 0,
                f"bank_seq[{i}]: PORTB ${portb:02X} has bit 0=1 (OS ROM ON)")
    
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


class TestDBANKTable(unittest.TestCase):
    """Verify DBANK_TABLE selects distinct physical banks for each memory tier.
    
    On different Atari memory expansions, different PORTB bits select banks:
      130XE (4 banks):  bits 2,3
      320k  (16 banks): bits 2,3,5,6
      1088k (64 banks): bits 1,2,3,5,6,7
    
    The first N entries in DBANK_TABLE must map to N distinct physical banks
    for every supported tier.
    """
    
    def test_130xe_4_banks_distinct(self):
        """First 4 entries must select 4 distinct banks on 130XE (bits 2,3)."""
        mask = 0x0C  # bits 2,3
        seen = set()
        for i in range(4):
            key = DBANK_TABLE[i] & mask
            self.assertNotIn(key, seen,
                f"DBANK_TABLE[{i}]=${DBANK_TABLE[i]:02X} aliases an earlier "
                f"entry on 130XE (bits 2,3 = {key>>2})")
            seen.add(key)
        self.assertEqual(len(seen), 4)
    
    def test_320k_16_banks_distinct(self):
        """First 16 entries must select 16 distinct banks on 320k RAMBO (bits 2,3,5,6)."""
        mask = 0x6C  # bits 2,3,5,6
        seen = set()
        for i in range(16):
            key = DBANK_TABLE[i] & mask
            self.assertNotIn(key, seen,
                f"DBANK_TABLE[{i}]=${DBANK_TABLE[i]:02X} aliases an earlier "
                f"entry on 320k RAMBO (bits 2,3,5,6)")
            seen.add(key)
        self.assertEqual(len(seen), 16)
    
    def test_1088k_64_banks_distinct(self):
        """All 64 entries must select 64 distinct banks on 1088k (bits 1,2,3,5,6,7)."""
        mask = 0xEE  # bits 1,2,3,5,6,7
        seen = set()
        for i in range(64):
            key = DBANK_TABLE[i] & mask
            self.assertNotIn(key, seen,
                f"DBANK_TABLE[{i}]=${DBANK_TABLE[i]:02X} aliases an earlier "
                f"entry on 1088k RAMBO (bits 1,2,3,5,6,7)")
            seen.add(key)
        self.assertEqual(len(seen), 64)
    
    def test_bit4_always_zero(self):
        """Bit 4 must be 0 in all entries (CPU bank enable)."""
        for i, v in enumerate(DBANK_TABLE):
            self.assertEqual(v & 0x10, 0,
                f"DBANK_TABLE[{i}]=${v:02X} has bit 4 set (bank disabled!)")
    
    def test_bit0_always_one(self):
        """Bit 0 must be 1 in raw table (OS ROM on for loading)."""
        for i, v in enumerate(DBANK_TABLE):
            self.assertEqual(v & 0x01, 1,
                f"DBANK_TABLE[{i}]=${v:02X} has bit 0=0 (OS ROM off during load)")
    
    def test_matches_reference_setpb(self):
        """DBANK_TABLE must match the reference setpb procedure output.
        
        setpb: X=%0000dcba -> PORTB=%cba000d1
        Blocks probed X=15 downto 0, 4 banks per block via bits 2,3.
        """
        expected = []
        for x in range(15, -1, -1):
            d = (x >> 3) & 1
            c = (x >> 2) & 1
            b = (x >> 1) & 1
            a = x & 1
            base = (c << 7) | (b << 6) | (a << 5) | (d << 1) | 1
            expected.extend([base, base ^ 0x04, base ^ 0x08, base ^ 0x0C])
        
        self.assertEqual(len(DBANK_TABLE), 64)
        for i in range(64):
            self.assertEqual(DBANK_TABLE[i], expected[i],
                f"DBANK_TABLE[{i}]=${DBANK_TABLE[i]:02X} != "
                f"expected ${expected[i]:02X} from setpb")


class TestPerBankCodebook(unittest.TestCase):
    """Tests for per-bank codebook support (codebook_size > 0).
    
    Two-phase packing: VQ instruments go into banks WITH codebook,
    RAW instruments go into banks WITHOUT codebook (full 16KB).
    Tests must pass vq_instruments to trigger codebook reservation.
    """
    
    def test_codebook_reserves_space(self):
        """With codebook_size=1024, VQ data starts after codebook."""
        cb_size = 1024  # 256 * vec_size=4
        r = pack_into_banks([(0, 5000)], codebook_size=cb_size,
                            vq_instruments={0})
        self.assertTrue(r.success)
        p = r.placements[0]
        # Data should start at $4000 + 1024 = $4400
        self.assertEqual(p.offset, BANK_BASE + cb_size)
    
    def test_codebook_reduces_capacity(self):
        """Per-bank codebook reduces effective bank capacity for VQ."""
        cb_size = 2048  # 256 * vec_size=8
        effective = BANK_SIZE - cb_size  # 14336 bytes
        # Fill slightly more than effective → needs 2 banks
        r = pack_into_banks([(0, effective + 100)], codebook_size=cb_size,
                            vq_instruments={0})
        self.assertTrue(r.success)
        self.assertEqual(r.placements[0].n_banks, 2)
    
    def test_codebook_two_vq_items_one_bank(self):
        """Two small VQ items fit in one bank after codebook."""
        cb_size = 1024
        r = pack_into_banks([(0, 7000), (1, 7000)], codebook_size=cb_size,
                            vq_instruments={0, 1})
        self.assertTrue(r.success)
        self.assertEqual(r.n_banks_used, 1)
        # Both offsets should be >= $4000 + codebook
        for p in r.placements.values():
            self.assertGreaterEqual(p.offset, BANK_BASE + cb_size)
    
    def test_codebook_end_addr_single(self):
        """End address accounts for codebook offset (single bank)."""
        cb_size = 1024
        data_size = 5000
        r = pack_into_banks([(0, data_size)], codebook_size=cb_size,
                            vq_instruments={0})
        p = r.placements[0]
        end = (p.end_addr_hi << 8) | p.end_addr_lo
        self.assertEqual(end, BANK_BASE + cb_size + data_size)
    
    def test_codebook_end_addr_multi(self):
        """End address in last bank accounts for codebook (multi-bank)."""
        cb_size = 1024
        effective = BANK_SIZE - cb_size
        extra = 2000
        data_size = effective + extra  # spans 2 banks
        r = pack_into_banks([(0, data_size)], codebook_size=cb_size,
                            vq_instruments={0})
        p = r.placements[0]
        self.assertEqual(p.n_banks, 2)
        end = (p.end_addr_hi << 8) | p.end_addr_lo
        # In last bank: data starts at $4000 + cb_size, uses 'extra' bytes
        self.assertEqual(end, BANK_BASE + cb_size + extra)
    
    def test_codebook_portb_bit0_cleared(self):
        """PORTB bit 0 still cleared with codebook."""
        cb_size = 1024
        items = [(0, 8000), (1, 20000)]
        r = pack_into_banks(items, codebook_size=cb_size,
                            vq_instruments={0, 1})
        for p in r.placements.values():
            for portb in p.portb_values:
                self.assertEqual(portb & 1, 0)
    
    def test_codebook_overflow_detection(self):
        """Codebook larger than bank size fails gracefully."""
        r = pack_into_banks([(0, 100)], codebook_size=BANK_SIZE + 1,
                            vq_instruments={0})
        self.assertFalse(r.success)
        self.assertIn("Codebook size", r.error)
    
    def test_raw_gets_full_capacity(self):
        """RAW instruments get full 16KB per bank even when codebook_size > 0."""
        cb_size = 2048
        # 962KB all-RAW: fits because RAW banks have full 16KB
        total_data = 962 * 1024
        r = pack_into_banks([(0, total_data)], max_banks=64,
                            codebook_size=cb_size, vq_instruments=set())
        self.assertTrue(r.success)  # RAW → 64 × 16KB = 1024KB > 962KB
    
    def test_vq_limited_raw_full(self):
        """VQ banks have codebook overhead, RAW banks don't."""
        cb_size = 2048
        vq_effective = BANK_SIZE - cb_size  # 14336
        # VQ instrument needs 2 banks (slightly over 1 effective)
        # RAW instrument fits in 1 full bank
        r = pack_into_banks([(0, vq_effective + 100), (1, 15000)],
                            codebook_size=cb_size, vq_instruments={0})
        self.assertTrue(r.success)
        self.assertEqual(r.placements[0].n_banks, 2)  # VQ: 2 banks
        self.assertEqual(r.placements[1].n_banks, 1)  # RAW: 1 bank
        self.assertEqual(r.n_banks_used, 3)
        # VQ banks have codebook, RAW bank doesn't
        self.assertTrue(r.bank_has_codebook[0])   # VQ bank
        self.assertTrue(r.bank_has_codebook[1])   # VQ bank
        self.assertFalse(r.bank_has_codebook[2])  # RAW bank
    
    def test_raw_address_starts_at_4000(self):
        """RAW data starts at $4000 even when codebook_size > 0."""
        r = pack_into_banks([(0, 1000)], codebook_size=2048,
                            vq_instruments=set())
        self.assertTrue(r.success)
        self.assertEqual(r.placements[0].offset, 0x4000)
    
    def test_vq_address_starts_at_4800(self):
        """VQ data starts at $4800 with codebook_size=2048."""
        r = pack_into_banks([(0, 1000)], codebook_size=2048,
                            vq_instruments={0})
        self.assertTrue(r.success)
        self.assertEqual(r.placements[0].offset, 0x4800)
    
    def test_mixed_vq_raw_no_cross_placement(self):
        """VQ items never placed in RAW banks and vice versa."""
        cb_size = 1024
        # Small VQ and RAW: both fit in one bank each, but must be separate
        r = pack_into_banks([(0, 4000), (1, 4000)],
                            codebook_size=cb_size, vq_instruments={0})
        self.assertTrue(r.success)
        # Must use 2 banks (VQ and RAW can't share)
        self.assertEqual(r.n_banks_used, 2)
        vq_bank = r.placements[0].bank_indices[0]
        raw_bank = r.placements[1].bank_indices[0]
        self.assertNotEqual(vq_bank, raw_bank)
        self.assertTrue(r.bank_has_codebook[vq_bank])
        self.assertFalse(r.bank_has_codebook[raw_bank])


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


class TestPerBankVQReEncoding(unittest.TestCase):
    """Tests for per-bank VQ re-encoding (build.py functions)."""
    
    def test_parse_vq_blob(self):
        """Parse VQ_BLOB.asm hex bytes."""
        import tempfile, os
        content = (
            "VQ_BLOB_LEN = 8\n"
            "VQ_BLOB\n"
            " .byte $10,$11,$12,$13,$14,$15,$16,$17\n"
        )
        with tempfile.NamedTemporaryFile(mode='w', suffix='.asm',
                                          delete=False) as f:
            f.write(content)
            path = f.name
        try:
            from build import _parse_vq_blob
            blob = _parse_vq_blob(path)
            self.assertEqual(len(blob), 8)
            self.assertEqual(blob[0], 0x10)
            self.assertEqual(blob[7], 0x17)
        finally:
            os.unlink(path)
    
    def test_parse_vq_blob_inline_comments(self):
        """Parse VQ_BLOB.asm with inline comments — last byte must not be lost."""
        import tempfile, os
        content = (
            "VQ_BLOB\n"
            " .byte $10,$11,$12,$13 ; entry 0\n"
            " .byte $14,$15,$16,$17 ; entry 1\n"
        )
        with tempfile.NamedTemporaryFile(mode='w', suffix='.asm',
                                          delete=False) as f:
            f.write(content)
            path = f.name
        try:
            from build import _parse_vq_blob
            blob = _parse_vq_blob(path)
            self.assertEqual(len(blob), 8,
                           f"Expected 8 bytes, got {len(blob)} (inline comment ate a byte?)")
            self.assertEqual(blob[3], 0x13)
            self.assertEqual(blob[7], 0x17)
        finally:
            os.unlink(path)
    
    def test_reencode_bank_vq_basic(self):
        """Re-encode preserves approximate volume levels."""
        import numpy as np
        from build import _reencode_bank_vq
        
        vec_size = 4
        # Build a simple 4-entry global codebook (AUDC format: $10|vol)
        # Entry 0: silence [0,0,0,0], Entry 1: [1,2,1,2], etc.
        global_cb = []
        for i in range(256):
            for j in range(vec_size):
                vol = min(15, (i + j) % 16)
                global_cb.append(0x10 | vol)
        
        # Create some indices referencing entries 0-3
        bank_indices = bytes([0, 1, 2, 3, 0, 0, 1, 1])
        
        cb_bytes, reenc = _reencode_bank_vq(bank_indices, global_cb, vec_size)
        
        self.assertEqual(len(cb_bytes), 256 * vec_size)
        self.assertEqual(len(reenc), len(bank_indices))
        # All codebook bytes should have AUDC mask
        for b in cb_bytes:
            self.assertEqual(b & 0x10, 0x10,
                           f"Codebook byte ${b:02X} missing AUDC mask $10")
    
    def test_reencode_silence_reserved(self):
        """Silence codebook[0] reserved when near-silent vectors exist."""
        import numpy as np
        from build import _reencode_bank_vq
        
        vec_size = 4
        # Global codebook: entry 0 = silence, entry 5 = loud
        global_cb = [0x10] * (256 * vec_size)  # all silence
        for j in range(vec_size):
            global_cb[5 * vec_size + j] = 0x1F  # entry 5 = max vol
        
        # Mix of silence (idx 0) and loud (idx 5)
        bank_indices = bytes([0, 0, 0, 5, 0, 5])
        
        cb_bytes, reenc = _reencode_bank_vq(bank_indices, global_cb, vec_size)
        
        # Codebook entry 0 should be silence ($10 for all samples)
        for j in range(vec_size):
            self.assertEqual(cb_bytes[j], 0x10,
                           f"Codebook[0][{j}] = ${cb_bytes[j]:02X}, expected $10")
    
    def test_generate_banking_vq_tables(self):
        """VQ_LO/VQ_HI point to $4000+idx*vec_size."""
        import tempfile, os
        from build import _generate_banking_vq_tables
        
        tmpdir = tempfile.mkdtemp()
        try:
            vec_size = 8
            _generate_banking_vq_tables(tmpdir, vec_size)
            
            lo_path = os.path.join(tmpdir, "VQ_LO.asm")
            hi_path = os.path.join(tmpdir, "VQ_HI.asm")
            self.assertTrue(os.path.exists(lo_path))
            self.assertTrue(os.path.exists(hi_path))
            
            # Parse and verify addresses
            with open(lo_path) as f:
                lo_content = f.read()
            with open(hi_path) as f:
                hi_content = f.read()
            
            self.assertIn("VQ_LO", lo_content)
            self.assertIn("VQ_HI", hi_content)
            # Entry 0 → $4000 (lo=$00, hi=$40)
            self.assertIn("$00", lo_content)
            self.assertIn("$40", hi_content)
        finally:
            import shutil
            shutil.rmtree(tmpdir)
    
    def test_reencode_order_two_instruments_same_bank(self):
        """Re-encoding with 2 instruments in same bank preserves data identity.
        
        This verifies the fix for the concatenation/split order bug: when
        multiple instruments share a bank, each instrument must get back
        its own re-encoded data (not the other's).
        """
        import numpy as np
        from build import _reencode_bank_vq
        
        vec_size = 4
        # Build global codebook: entry 0 = silence, entry 10 = loud
        global_cb = [0x10] * (256 * vec_size)  # all silence by default
        for j in range(vec_size):
            global_cb[10 * vec_size + j] = 0x1F  # entry 10 = max vol
        
        # Instrument A: all silence (index 0)
        inst_a_indices = bytes([0] * 50)
        # Instrument B: all loud (index 10)
        inst_b_indices = bytes([10] * 30)
        
        # Concatenate in order A, B (as the build pipeline would)
        combined = inst_a_indices + inst_b_indices
        
        cb_bytes, reencoded = _reencode_bank_vq(combined, global_cb, vec_size)
        
        # Split back: A gets first 50, B gets next 30
        reenc_a = reencoded[:50]
        reenc_b = reencoded[50:80]
        
        # Instrument A (silence) should all map to the same codebook entry
        # (likely entry 0, the silence entry)
        unique_a = set(reenc_a)
        self.assertEqual(len(unique_a), 1,
                        f"Silent inst A should have 1 unique index, got {len(unique_a)}")
        
        # Instrument B (loud) should all map to a DIFFERENT entry
        unique_b = set(reenc_b)
        self.assertEqual(len(unique_b), 1,
                        f"Loud inst B should have 1 unique index, got {len(unique_b)}")
        
        # A and B should map to different codebook entries
        self.assertNotEqual(unique_a, unique_b,
                           "Silence and loud instruments must use different codebook entries")
        
        # Verify the codebook entry for A is silence ($10 = vol 0)
        idx_a = list(unique_a)[0]
        for j in range(vec_size):
            self.assertEqual(cb_bytes[idx_a * vec_size + j], 0x10,
                           f"Codebook[{idx_a}][{j}] should be $10 (silence)")
        
        # Verify the codebook entry for B is loud ($1F = vol 15)
        idx_b = list(unique_b)[0]
        for j in range(vec_size):
            self.assertEqual(cb_bytes[idx_b * vec_size + j], 0x1F,
                           f"Codebook[{idx_b}][{j}] should be $1F (loud)")


class TestVerifyBankingFit(unittest.TestCase):
    """Tests for optimizer's trial-pack verification with bank packer."""

    def test_fragmentation_demotion(self):
        """Large RAW instruments that cause fragmentation should be demoted to VQ."""
        from optimize import _verify_banking_fit, OptimizeResult, InstrumentAnalysis

        # Reproduce the user's exact scenario: 22 instruments, 16 banks
        inst_data = [
            (0, 1024, False), (1, 3840, False), (2, 4096, False),
            (3, 5120, False), (4, 6656, False), (5, 7424, False),
            (6, 38912, False), (7, 2816, False), (8, 3584, False),
            (9, 3584, False), (10, 1024, False), (11, 5376, False),
            (12, 6144, False),
            (13, 10570, True), (14, 69376, False),
            (15, 10176, True), (16, 9503, True), (17, 12720, True),
            (18, 12800, False), (19, 8960, False),
            (20, 12544, False), (21, 17664, False),
        ]

        max_banks = 16
        codebook_size = 2048
        vector_size = 8
        result = OptimizeResult(memory_budget=max_banks * BANK_SIZE)
        mode_map = {}

        for idx, sz, is_vq in inst_data:
            a = InstrumentAnalysis(index=idx, name=f"inst_{idx}")
            a.raw_size_aligned = sz
            a.vq_size = sz // 8 if not is_vq else sz
            a.suggest_raw = not is_vq
            mode_map[idx] = not is_vq
            result.analyses.append(a)

        # Without verification: 18 RAW, packer needs 18 banks > 16
        self.assertEqual(sum(1 for a in result.analyses if a.suggest_raw), 18)

        _verify_banking_fit(result, mode_map, codebook_size, max_banks,
                            [], vector_size, False, 30000)

        # After verification: some instruments demoted to VQ
        n_raw = sum(1 for a in result.analyses if a.suggest_raw)
        self.assertLess(n_raw, 18, "Should have demoted at least one RAW to VQ")

        # Final state must pack successfully
        inst_sizes = [(a.index, a.raw_size_aligned if a.suggest_raw else a.vq_size)
                      for a in result.analyses
                      if (a.raw_size_aligned if a.suggest_raw else a.vq_size) > 0]
        vq_set = {a.index for a in result.analyses if not a.suggest_raw}
        pack = pack_into_banks(inst_sizes, max_banks,
                               codebook_size=codebook_size,
                               vq_instruments=vq_set)
        self.assertTrue(pack.success, f"Pack should succeed after demotion: {pack.error}")
        self.assertLessEqual(pack.n_banks_used, max_banks)

    def test_no_demotion_when_fits(self):
        """No instruments should be demoted if pack already succeeds."""
        from optimize import _verify_banking_fit, OptimizeResult, InstrumentAnalysis

        max_banks = 16
        codebook_size = 2048
        result = OptimizeResult(memory_budget=max_banks * BANK_SIZE)
        mode_map = {}

        # 4 small RAW instruments — easily fits
        for i in range(4):
            a = InstrumentAnalysis(index=i, name=f"inst_{i}")
            a.raw_size_aligned = 4096
            a.vq_size = 512
            a.suggest_raw = True
            mode_map[i] = True
            result.analyses.append(a)

        _verify_banking_fit(result, mode_map, codebook_size, max_banks,
                            [], 8, False, 30000)

        # All should remain RAW
        self.assertTrue(all(a.suggest_raw for a in result.analyses))


if __name__ == '__main__':
    unittest.main()
