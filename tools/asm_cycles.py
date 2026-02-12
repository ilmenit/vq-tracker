#!/usr/bin/env python3
"""6502 Cycle Analyzer for MADS-syntax assembly.

Preprocesses MADS source (icl includes, .if/.ifdef/.elif/.else/.endif
conditionals, symbol = value definitions, .macro/.endm), then counts
exact cycle costs per instruction and reports per-path totals.

IMPORTANT: For accurate results, either:
  1. Process the top-level file (song_player.asm) which includes everything, or
  2. Use -P to pre-include symbol definition files (zeropage.inc, atari.inc)

Usage:
    # Best: process top-level (all symbols auto-resolved)
    python tools/asm_cycles.py asm/song_player.asm \\
        -D TRACKER=1 OPTIMIZE_SPEED=1 MULTI_SAMPLE=1 PITCH_CONTROL=1 \\
           ALGO_FIXED=1 MIN_VECTOR=8 IRQ_MASK=1 VOLUME_CONTROL=1 \\
           BLANK_SCREEN=0 KEY_CONTROL=0 AUDCTL_VAL=0 \\
        -I asm

    # Alternative: pre-include symbol files
    python tools/asm_cycles.py asm/tracker/tracker_irq_speed.asm \\
        -P asm/common/zeropage.inc -P asm/common/atari.inc \\
        -D TRACKER=1 VOLUME_CONTROL=1 MIN_VECTOR=8 IRQ_MASK=1 \\
        -I asm

    # Compare all VOLUME_CONTROL × MIN_VECTOR configs
    python tools/asm_cycles.py asm/song_player.asm \\
        -D TRACKER=1 OPTIMIZE_SPEED=1 MULTI_SAMPLE=1 PITCH_CONTROL=1 \\
           ALGO_FIXED=1 BLANK_SCREEN=0 KEY_CONTROL=0 AUDCTL_VAL=0 \\
        -I asm --all-configs

    # Detailed section analysis
    python tools/asm_cycles.py asm/song_player.asm \\
        <defines as above> -I asm \\
        -s Tracker_IRQ @skip_ch0

    # Annotated listing with per-instruction cycle counts
    python tools/asm_cycles.py asm/song_player.asm \\
        <defines as above> -I asm --annotate
"""

import re
import os
import sys
import argparse
from typing import Dict, List, Optional, Tuple, Set


# ============================================================================
# 6502 CYCLE TABLE — complete, authoritative
# ============================================================================
# Source: MOS 6502 datasheet + "6502 Programming Manual"
#
# For read-modify instructions (LDA, LDX, LDY, CMP, CPX, CPY, ADC, SBC,
# AND, ORA, EOR, BIT) with indexed absolute modes (abx, aby):
#   base cycles shown; +1 if indexing crosses a page boundary.
# For store/RMW instructions (STA, STX, STY, INC, DEC, ASL, LSR, ROL, ROR)
# with indexed absolute: always takes the extra cycle (no +1 conditional).

CYCLES = {
    # --- Loads ---
    ('LDA','imm'):2, ('LDA','zp'):3, ('LDA','zpx'):4,
    ('LDA','abs'):4, ('LDA','abx'):4, ('LDA','aby'):4,  # +1 page cross
    ('LDA','izx'):6, ('LDA','izy'):5,                    # izy: +1 page cross
    ('LDX','imm'):2, ('LDX','zp'):3, ('LDX','zpy'):4,
    ('LDX','abs'):4, ('LDX','aby'):4,                    # +1 page cross
    ('LDY','imm'):2, ('LDY','zp'):3, ('LDY','zpx'):4,
    ('LDY','abs'):4, ('LDY','abx'):4,                    # +1 page cross
    # --- Stores ---
    ('STA','zp'):3,  ('STA','zpx'):4,
    ('STA','abs'):4, ('STA','abx'):5, ('STA','aby'):5,   # always 5
    ('STA','izx'):6, ('STA','izy'):6,                    # always 6
    ('STX','zp'):3,  ('STX','zpy'):4, ('STX','abs'):4,
    ('STY','zp'):3,  ('STY','zpx'):4, ('STY','abs'):4,
    # --- Arithmetic ---
    ('ADC','imm'):2, ('ADC','zp'):3, ('ADC','zpx'):4,
    ('ADC','abs'):4, ('ADC','abx'):4, ('ADC','aby'):4,   # +1 page cross
    ('ADC','izx'):6, ('ADC','izy'):5,                    # izy: +1 page cross
    ('SBC','imm'):2, ('SBC','zp'):3, ('SBC','zpx'):4,
    ('SBC','abs'):4, ('SBC','abx'):4, ('SBC','aby'):4,   # +1 page cross
    ('SBC','izx'):6, ('SBC','izy'):5,                    # izy: +1 page cross
    # --- Compare ---
    ('CMP','imm'):2, ('CMP','zp'):3, ('CMP','zpx'):4,
    ('CMP','abs'):4, ('CMP','abx'):4, ('CMP','aby'):4,   # +1 page cross
    ('CMP','izx'):6, ('CMP','izy'):5,
    ('CPX','imm'):2, ('CPX','zp'):3, ('CPX','abs'):4,
    ('CPY','imm'):2, ('CPY','zp'):3, ('CPY','abs'):4,
    # --- Logic ---
    ('AND','imm'):2, ('AND','zp'):3, ('AND','zpx'):4,
    ('AND','abs'):4, ('AND','abx'):4, ('AND','aby'):4,   # +1 page cross
    ('AND','izx'):6, ('AND','izy'):5,
    ('ORA','imm'):2, ('ORA','zp'):3, ('ORA','zpx'):4,
    ('ORA','abs'):4, ('ORA','abx'):4, ('ORA','aby'):4,   # +1 page cross
    ('ORA','izx'):6, ('ORA','izy'):5,
    ('EOR','imm'):2, ('EOR','zp'):3, ('EOR','zpx'):4,
    ('EOR','abs'):4, ('EOR','abx'):4, ('EOR','aby'):4,   # +1 page cross
    ('EOR','izx'):6, ('EOR','izy'):5,
    ('BIT','zp'):3,  ('BIT','abs'):4,
    # --- Shifts / Rotates ---
    ('ASL','acc'):2, ('ASL','zp'):5, ('ASL','zpx'):6,
    ('ASL','abs'):6, ('ASL','abx'):7,                    # RMW: always 7
    ('LSR','acc'):2, ('LSR','zp'):5, ('LSR','zpx'):6,
    ('LSR','abs'):6, ('LSR','abx'):7,
    ('ROL','acc'):2, ('ROL','zp'):5, ('ROL','zpx'):6,
    ('ROL','abs'):6, ('ROL','abx'):7,
    ('ROR','acc'):2, ('ROR','zp'):5, ('ROR','zpx'):6,
    ('ROR','abs'):6, ('ROR','abx'):7,
    # --- Inc/Dec ---
    ('INC','zp'):5,  ('INC','zpx'):6, ('INC','abs'):6, ('INC','abx'):7,
    ('DEC','zp'):5,  ('DEC','zpx'):6, ('DEC','abs'):6, ('DEC','abx'):7,
    ('INX','imp'):2, ('INY','imp'):2, ('DEX','imp'):2, ('DEY','imp'):2,
    # --- Branches ---
    # 2 = not taken; +1 taken same page; +2 taken cross page
    ('BCC','rel'):2, ('BCS','rel'):2, ('BEQ','rel'):2, ('BNE','rel'):2,
    ('BMI','rel'):2, ('BPL','rel'):2, ('BVC','rel'):2, ('BVS','rel'):2,
    # --- Jumps/Calls ---
    ('JMP','abs'):3, ('JMP','ind'):5,
    ('JSR','abs'):6, ('RTS','imp'):6, ('RTI','imp'):6,
    # --- Stack ---
    ('PHA','imp'):3, ('PLA','imp'):4, ('PHP','imp'):3, ('PLP','imp'):4,
    # --- Flags ---
    ('CLC','imp'):2, ('SEC','imp'):2, ('CLI','imp'):2, ('SEI','imp'):2,
    ('CLV','imp'):2, ('CLD','imp'):2, ('SED','imp'):2,
    # --- Transfer ---
    ('TAX','imp'):2, ('TAY','imp'):2, ('TXA','imp'):2, ('TYA','imp'):2,
    ('TSX','imp'):2, ('TXS','imp'):2,
    # --- NOP/BRK ---
    ('NOP','imp'):2, ('BRK','imp'):7,
}

# Modes eligible for +1 page-cross penalty (reads only)
PAGE_CROSS_MODES = {'abx', 'aby', 'izy'}

# Read instructions (eligible for page-cross +1)
READ_MNEMONICS = {
    'LDA','LDX','LDY','CMP','CPX','CPY',
    'ADC','SBC','AND','ORA','EOR','BIT',
}

IMPLIED_MNEMONICS = {
    'CLC','SEC','CLI','SEI','CLV','CLD','SED',
    'TAX','TAY','TXA','TYA','TSX','TXS',
    'PHA','PLA','PHP','PLP','INX','INY','DEX','DEY',
    'RTS','RTI','BRK','NOP',
}
BRANCH_MNEMONICS = {'BCC','BCS','BEQ','BNE','BMI','BPL','BVC','BVS'}
ACC_MNEMONICS = {'ASL','LSR','ROL','ROR'}
ALL_MNEMONICS = {m for m, _ in CYCLES}


# ============================================================================
# ANTIC DMA MODEL — Atari 8-bit specific
# ============================================================================

class DmaModel:
    """Compute CPU cycles available per IRQ period under different
    ANTIC display configurations.

    ANTIC steals CPU cycles for memory refresh, display list fetch,
    character name fetch, and display data (font/bitmap) fetch.
    The amount varies per scanline depending on the display mode.
    """

    # Cycles stolen per scanline by source
    REFRESH = 9          # Memory refresh: always, every scanline
    DL_FETCH = 1         # Display list instruction: first scanline of mode line

    # Per-scanline display data stealing by ANTIC mode
    # (for normal width; wide adds ~10%, narrow subtracts ~10%)
    # Format: (first_line_steal, other_line_steal)
    # first_line includes character name fetch + data; other is data only
    MODES = {
        'blank':   (0, 0),
        'gr0':     (40+40, 40),   # char names + font / font only
        'gr1':     (20+40, 40),   # 20-col char names + font
        'gr2':     (20+40, 40),   # same as gr1
        'gr7':     (40, 40),      # 4-color bitmap, 40 bytes/line
        'gr8':     (40, 40),      # hires bitmap, 40 bytes/line
        'gr15':    (20, 20),      # 4-color, 20 bytes/line
    }

    # Player/missile DMA (if enabled): 5 cycles/scanline for single-line
    # resolution, 1 cycle for double-line. We'll offer this as a flag.

    @classmethod
    def cycles_per_scanline(cls, mode='gr0', is_first_of_row=False,
                            is_display=True, pm_enabled=False):
        """Return CPU cycles available on one scanline."""
        total = 114
        total -= cls.REFRESH
        if not is_display:
            return total  # vblank: only refresh
        total -= cls.DL_FETCH
        if pm_enabled:
            total -= 5
        mode_steal = cls.MODES.get(mode, cls.MODES['gr0'])
        if is_first_of_row:
            total -= mode_steal[0]
        else:
            total -= mode_steal[1]
        return max(total, 0)

    @classmethod
    def effective_ratio(cls, mode='gr0', scenario='average'):
        """Return fraction of machine cycles available to CPU.

        Scenarios:
          'average'  - weighted average across full frame
          'worst'    - worst-case scanline (first-of-row in display)
          'best'     - best display scanline (non-first-of-row)
          'vblank'   - during vertical blank
          'no_dma'   - DMA disabled (blank display list)
        """
        if scenario == 'no_dma':
            return (114 - cls.REFRESH) / 114

        if scenario == 'vblank':
            return (114 - cls.REFRESH) / 114

        if scenario == 'worst':
            avail = cls.cycles_per_scanline(mode, is_first_of_row=True)
            return avail / 114

        if scenario == 'best':
            avail = cls.cycles_per_scanline(mode, is_first_of_row=False)
            return avail / 114

        # Average: compute across full NTSC frame
        # 24 text rows × 8 scanlines = 192 display lines
        # 70 vblank lines (NTSC: 262 total)
        first_avail = cls.cycles_per_scanline(mode, True)
        other_avail = cls.cycles_per_scanline(mode, False)
        vblank_avail = 114 - cls.REFRESH

        n_rows = 24  # typical GR.0 screen
        lines_per_row = 8
        n_display = n_rows * lines_per_row  # 192
        n_vblank = 262 - n_display          # 70

        total_cpu = (n_rows * first_avail +
                     n_rows * (lines_per_row - 1) * other_avail +
                     n_vblank * vblank_avail)
        total_machine = 262 * 114
        return total_cpu / total_machine

    @classmethod
    def budget_table(cls, handler_min, handler_max, mode='gr0'):
        """Generate a formatted budget table for various rates."""
        lines = []
        hdr = (f"  {'Rate':>6s}  {'Mach':>5s}  "
               f"{'Avg':>5s} {'Worst':>5s} {'VBlnk':>5s}  "
               f"{'%Avg':>5s} {'%Wrst':>6s}  {'Status':>8s}")
        sep = (f"  {'─'*6}  {'─'*5}  "
               f"{'─'*5} {'─'*5} {'─'*5}  "
               f"{'─'*5} {'─'*6}  {'─'*8}")
        lines.append(hdr)
        lines.append(sep)

        for rate in [4000, 5000, 5500, 6000, 7000, 8000]:
            mach = 1789773 / rate
            avg = mach * cls.effective_ratio(mode, 'average')
            worst = mach * cls.effective_ratio(mode, 'worst')
            vbl = mach * cls.effective_ratio(mode, 'vblank')

            pct_avg = handler_max / avg * 100
            pct_worst = handler_max / worst * 100

            if pct_avg > 100:
                status = "OVER"
            elif pct_avg > 85:
                status = "TIGHT"
            else:
                status = "OK"

            lines.append(
                f"  {rate:5d}Hz  {mach:5.0f}  "
                f"{avg:5.0f} {worst:5.0f} {vbl:5.0f}  "
                f"{pct_avg:4.0f}% {pct_worst:5.0f}%  "
                f"  {status}")

        return '\n'.join(lines)


# ============================================================================
# MADS PREPROCESSOR
# ============================================================================

class MadsPreprocessor:
    """Preprocess MADS assembly: resolve icl includes, conditionals, symbols."""

    def __init__(self, include_dirs=None, defines=None):
        self.include_dirs = include_dirs or ['.']
        self.symbols: Dict[str, int] = dict(defines) if defines else {}
        self.macros: Dict[str, List[str]] = {}
        self._included: Set[str] = set()
        self.warnings: List[str] = []

    def process_file(self, path: str) -> List[Tuple[str, str, int]]:
        """Process file. Returns [(line_text, source_file, source_lineno)]."""
        abs_path = os.path.abspath(path)
        if abs_path in self._included:
            return []
        self._included.add(abs_path)
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                raw_lines = f.readlines()
        except FileNotFoundError:
            self.warnings.append(f"File not found: {path}")
            return []
        base_dir = os.path.dirname(abs_path)
        return self._process_lines(raw_lines, path, base_dir)

    def _process_lines(self, lines, source_file, base_dir):
        output = []
        cond_stack = []   # [(active, any_branch_taken)]
        in_macro = None
        macro_body = []

        for line_num, raw in enumerate(lines, 1):
            line = raw.rstrip('\n\r')
            code = self._strip_comment(line).strip()

            # Macro body collection
            if in_macro is not None:
                if code.lower().startswith('.endm'):
                    self.macros[in_macro] = macro_body
                    in_macro = None
                    macro_body = []
                else:
                    macro_body.append(line)
                continue

            active = all(a for a, _ in cond_stack)

            # Conditionals — always processed regardless of active state
            if self._handle_conditional(code, cond_stack, source_file, line_num):
                continue

            if not active:
                continue

            # Macro definition start
            m = re.match(r'\.macro\s+(\w+)', code, re.I)
            if m:
                in_macro = m.group(1).upper()
                macro_body = []
                continue

            # Include: icl "path"
            m = re.match(r'icl\s+"([^"]+)"', code, re.I)
            if m:
                inc_path = m.group(1)
                resolved = self._resolve_include(inc_path, base_dir)
                if resolved:
                    output.extend(self.process_file(resolved))
                else:
                    self.warnings.append(
                        f"{source_file}:{line_num}: include not found: {inc_path}")
                continue

            # Symbol definition: NAME = expr
            m = re.match(r'(\w+)\s*=\s*(.+)', code)
            if m:
                name, expr = m.group(1), m.group(2).strip()
                if expr != '*':
                    val = self._eval_expr(expr)
                    if val is not None:
                        self.symbols[name] = val
                output.append((line, source_file, line_num))
                continue

            # .error
            if code.lower().startswith('.error'):
                self.warnings.append(f"{source_file}:{line_num}: {code}")
                continue

            # Everything else: pass through
            output.append((line, source_file, line_num))

        return output

    def _handle_conditional(self, code, stack, src, ln):
        low = code.lower()

        if low.startswith('.if ') and not low.startswith('.ifdef') \
                and not low.startswith('.ifndef'):
            result = self._eval_condition(code[4:])
            parent = all(a for a, _ in stack)
            stack.append((parent and result, result))
            return True

        if low.startswith('.ifdef '):
            name = code[7:].strip()
            exists = name in self.symbols
            parent = all(a for a, _ in stack)
            stack.append((parent and exists, exists))
            return True

        if low.startswith('.ifndef '):
            name = code[8:].strip()
            exists = name in self.symbols
            parent = all(a for a, _ in stack)
            stack.append((parent and not exists, not exists))
            return True

        if low.startswith('.elif '):
            if not stack:
                return True
            result = self._eval_condition(code[6:])
            _, any_taken = stack[-1]
            parent = all(a for a, _ in stack[:-1])
            stack[-1] = (parent and result and not any_taken,
                         any_taken or result)
            return True

        if low.startswith('.else'):
            if not stack:
                return True
            _, any_taken = stack[-1]
            parent = all(a for a, _ in stack[:-1])
            stack[-1] = (parent and not any_taken, True)
            return True

        if low.startswith('.endif') or low.startswith('.fi'):
            if stack:
                stack.pop()
            return True

        return False

    def _eval_condition(self, expr):
        expr = expr.strip()
        # SYMBOL = VALUE (comparison in MADS .if)
        m = re.match(r'(\w+)\s*=\s*(.+)', expr)
        if m:
            left = self._eval_expr(m.group(1))
            right = self._eval_expr(m.group(2).strip())
            return left == right if left is not None and right is not None else False
        # SYMBOL <> VALUE
        m = re.match(r'(\w+)\s*<>\s*(.+)', expr)
        if m:
            left = self._eval_expr(m.group(1))
            right = self._eval_expr(m.group(2).strip())
            return left != right if left is not None and right is not None else False
        # Single symbol: nonzero = true
        val = self._eval_expr(expr)
        return bool(val) if val is not None else False

    def _eval_expr(self, expr):
        expr = expr.strip()
        if not expr:
            return None
        # Hex
        m = re.match(r'^\$([0-9A-Fa-f]+)$', expr)
        if m:
            return int(m.group(1), 16)
        # Decimal
        m = re.match(r'^(\d+)$', expr)
        if m:
            return int(m.group(1))
        # Symbol
        if re.match(r'^[A-Za-z_]\w*$', expr):
            return self.symbols.get(expr)
        # Low/high byte
        if expr.startswith('<'):
            v = self._eval_expr(expr[1:])
            return (v & 0xFF) if v is not None else None
        if expr.startswith('>'):
            v = self._eval_expr(expr[1:])
            return ((v >> 8) & 0xFF) if v is not None else None
        # Binary: A + B, A - B
        for op_ch, op_fn in [('+', lambda a, b: a+b), ('-', lambda a, b: a-b)]:
            pos = expr.rfind(op_ch)
            if pos > 0:
                left = self._eval_expr(expr[:pos])
                right = self._eval_expr(expr[pos+1:])
                if left is not None and right is not None:
                    return op_fn(left, right)
        return None

    def _resolve_include(self, path, base_dir):
        for d in [base_dir] + self.include_dirs:
            c = os.path.join(d, path)
            if os.path.exists(c):
                return c
        return None

    def _strip_comment(self, line):
        in_q = False
        for i, ch in enumerate(line):
            if ch == '"':
                in_q = not in_q
            elif ch == ';' and not in_q:
                return line[:i]
        return line


# ============================================================================
# INSTRUCTION PARSER
# ============================================================================

class InstructionParser:
    """Parse 6502 instructions, detect addressing modes via symbol resolution."""

    def __init__(self, symbols):
        self.symbols = symbols
        self.unresolved: Set[str] = set()  # track unknown symbols

    def parse_line(self, line):
        """Returns dict or None."""
        stripped = self._strip_comment(line).strip()
        if not stripped:
            return None

        label = None
        rest = stripped

        # Symbol definition line: NAME = expr
        if '=' in rest:
            eq_pos = rest.index('=')
            before = rest[:eq_pos].strip()
            if re.match(r'^@?\w+$', before):
                if not any(rest.upper().startswith(m + ' ') for m in ALL_MNEMONICS):
                    return self._label_only(before, line,
                                            is_smc=('= *' in rest))

        # Label at start of line
        m = re.match(r'^(@?\w+):?\s*(.*)', rest)
        if m:
            candidate = m.group(1)
            after = m.group(2).strip()
            if candidate.upper() not in ALL_MNEMONICS or candidate.startswith('@'):
                if not after:
                    return self._label_only(candidate.rstrip(':'), line)
                label = candidate.rstrip(':')
                rest = after

        # Skip directives
        if re.match(r'\.(byte|word|ds|dta|org|run|ini|align|print|proc|endp'
                    r'|local|endl|macro|endm)', rest, re.I):
            return None
        if re.match(r'icl\s', rest, re.I):
            return None

        # Parse mnemonic + operand
        parts = rest.split(None, 1)
        if not parts:
            return self._label_only(label, line) if label else None

        mnemonic = parts[0].upper()
        operand = self._strip_comment(parts[1]).strip() if len(parts) > 1 else ''

        if mnemonic not in ALL_MNEMONICS:
            return self._label_only(label, line) if label else None

        mode, branch_target = self._detect_mode(mnemonic, operand)
        base_cyc = CYCLES.get((mnemonic, mode), 0)
        taken_cyc = (base_cyc + 1) if mnemonic in BRANCH_MNEMONICS else 0

        # Page-cross potential
        page_cross = (mode in PAGE_CROSS_MODES and mnemonic in READ_MNEMONICS)

        return {
            'label': label, 'mnemonic': mnemonic, 'mode': mode,
            'operand': operand, 'cycles': base_cyc,
            'cycles_taken': taken_cyc,
            'cycles_page_cross': base_cyc + 1 if page_cross else base_cyc,
            'branch_target': branch_target,
            'is_branch': mnemonic in BRANCH_MNEMONICS,
            'is_jump': mnemonic in ('JMP', 'JSR'),
            'is_return': mnemonic in ('RTS', 'RTI'),
            'raw_line': line, 'is_smc': False,
            'page_cross_possible': page_cross,
        }

    def _label_only(self, name, line, is_smc=False):
        return {
            'label': name, 'mnemonic': None, 'mode': None,
            'operand': '', 'cycles': 0, 'cycles_taken': 0,
            'cycles_page_cross': 0,
            'branch_target': None, 'is_branch': False,
            'is_jump': False, 'is_return': False,
            'raw_line': line, 'is_smc': is_smc,
            'page_cross_possible': False,
        }

    def _detect_mode(self, mn, op):
        op = op.strip()
        # Accumulator-capable with no operand → accumulator mode
        if not op:
            if mn in ACC_MNEMONICS:
                return ('acc', None)
            return ('imp', None)
        # Implied (no operand for these)
        if mn in IMPLIED_MNEMONICS:
            return ('imp', None)
        # Explicit accumulator: ASL A
        if mn in ACC_MNEMONICS and op.upper() in ('A', '@'):
            return ('acc', None)
        # Branch: always relative
        if mn in BRANCH_MNEMONICS:
            return ('rel', op)
        # Immediate: #expr
        if op.startswith('#'):
            return ('imm', None)
        # (zp),Y
        m = re.match(r'\(([^)]+)\)\s*,\s*[Yy]', op)
        if m:
            return ('izy', None)
        # (zp,X)
        m = re.match(r'\(([^)]+)\s*,\s*[Xx]\s*\)', op)
        if m:
            return ('izx', None)
        # (addr) — indirect, only JMP
        m = re.match(r'\(([^)]+)\)', op)
        if m:
            return ('ind', None)
        # addr,X or addr,Y
        m = re.match(r'(.+)\s*,\s*([XxYy])', op)
        if m:
            base, reg = m.group(1).strip(), m.group(2).upper()
            zp = self._is_zp(base)
            if reg == 'X':
                return ('zpx' if zp else 'abx', None)
            return ('zpy' if zp else 'aby', None)
        # JMP/JSR always absolute
        if mn in ('JMP', 'JSR'):
            return ('abs', op)
        # Plain operand: zero-page or absolute
        return ('zp' if self._is_zp(op) else 'abs', None)

    def _is_zp(self, expr):
        expr = expr.strip()
        # Hex literal
        m = re.match(r'^\$([0-9A-Fa-f]+)$', expr)
        if m:
            return len(m.group(1)) <= 2 and int(m.group(1), 16) <= 0xFF
        # Decimal
        m = re.match(r'^(\d+)$', expr)
        if m:
            return int(m.group(1)) <= 0xFF
        # Symbol
        if re.match(r'^[A-Za-z_]\w*$', expr):
            val = self.symbols.get(expr)
            if val is not None:
                return 0 <= val <= 0xFF
            self.unresolved.add(expr)
            return False  # unknown → assume absolute (conservative)
        # Symbol+offset  (e.g. trk0_pitch_step+1)
        m = re.match(r'^(\w+)\s*\+\s*(\d+)$', expr)
        if m:
            val = self.symbols.get(m.group(1))
            if val is not None:
                return 0 <= (val + int(m.group(2))) <= 0xFF
            self.unresolved.add(m.group(1))
            return False
        return False

    def _strip_comment(self, line):
        in_q = False
        for i, ch in enumerate(line):
            if ch == '"': in_q = not in_q
            elif ch == ';' and not in_q: return line[:i]
        return line


# ============================================================================
# PATH ANALYZER
# ============================================================================

class PathAnalyzer:
    """Enumerate code paths between labels, compute cycle costs."""

    def __init__(self, parsed):
        self.lines = parsed
        self.label_idx = {}
        for i, info in enumerate(parsed):
            if info and info.get('label'):
                self.label_idx[info['label']] = i

    def trace_path(self, start, end, branch_taken=None):
        """Trace one path. Returns (total_cycles, [(desc, cycles)])."""
        if branch_taken is None:
            branch_taken = {}
        si = self.label_idx.get(start)
        ei = self.label_idx.get(end)
        if si is None or ei is None:
            return -1, []

        total, trace = 0, []
        i = si
        visited = set()

        while i < len(self.lines):
            if i in visited:
                break  # loop — stop silently
            visited.add(i)

            info = self.lines[i]
            if info is None:
                i += 1
                continue

            # Reached end label?
            if info.get('label') == end and i > si:
                break

            if not info.get('mnemonic'):
                i += 1
                continue

            mn = info['mnemonic']
            cyc = info['cycles']
            desc = f"{mn:4s} {info['operand']}"

            if info['is_branch']:
                tgt = info.get('branch_target', '')
                taken = branch_taken.get(tgt, False)
                if taken:
                    cyc = info['cycles_taken']
                    desc += " [TAKEN]"
                    trace.append((desc, cyc))
                    total += cyc
                    if tgt in self.label_idx:
                        i = self.label_idx[tgt]
                        continue
                    break
                else:
                    trace.append((desc, cyc))
                    total += cyc
                    i += 1
                    continue

            elif info['is_jump']:
                trace.append((desc, cyc))
                total += cyc
                tgt = info.get('operand', '').strip()
                if tgt in self.label_idx:
                    i = self.label_idx[tgt]
                    continue
                break

            elif info['is_return']:
                trace.append((desc, cyc))
                total += cyc
                break

            trace.append((desc, cyc))
            total += cyc
            i += 1

        return total, trace

    def enumerate_paths(self, start, end, max_branches=10):
        """Enumerate all branch combinations. Returns sorted by cycles."""
        si = self.label_idx.get(start, 0)
        ei = self.label_idx.get(end, len(self.lines))

        # Collect branch targets reachable from start
        targets = []
        for i in range(si, min(ei + 100, len(self.lines))):
            info = self.lines[i]
            if info and info.get('is_branch') and info.get('branch_target'):
                t = info['branch_target']
                if t not in targets:
                    targets.append(t)
        targets = targets[:max_branches]

        if not targets:
            cyc, tr = self.trace_path(start, end)
            return [{'cycles': cyc, 'trace': tr, 'choices': {}}]

        results = []
        seen_cycles = set()
        for bits in range(1 << len(targets)):
            choices = {t: bool(bits & (1 << j)) for j, t in enumerate(targets)}
            cyc, tr = self.trace_path(start, end, choices)
            if cyc >= 0 and cyc not in seen_cycles:
                seen_cycles.add(cyc)
                results.append({'cycles': cyc, 'trace': tr, 'choices': choices})

        results.sort(key=lambda r: r['cycles'])
        return results


# ============================================================================
# IRQ SUMMARY (with fixed channel detection)
# ============================================================================

def irq_summary(parsed, defines):
    """Auto-detect and summarize the IRQ handler with accurate DMA model."""
    labels = [p['label'] for p in parsed if p and p.get('label')]

    if 'Tracker_IRQ' not in labels:
        return "  Tracker_IRQ label not found."

    skips = sorted([l for l in labels if l.startswith('@skip_ch')])
    if not skips:
        return "  No @skip_chN labels found."

    analyzer = PathAnalyzer(parsed)
    lines = []

    # Channel analysis:
    # Ch0: Tracker_IRQ → @skip_ch0  (includes save regs + IRQEN overhead)
    # Ch1: @skip_ch0 → @skip_ch1    (the section AFTER skip_ch0)
    # Ch2: @skip_ch1 → @skip_ch2
    # Ch3: @skip_ch2 → @skip_ch3
    # Exit: @skip_ch3 → RTI         (restore regs)
    #
    # The overhead (save regs, IRQEN) is inside Ch0's range.
    # Each "channel" section includes the channel-inactive test + skip.

    ch_ranges = []
    ch_ranges.append(('Tracker_IRQ', skips[0], 'Ch0 (incl overhead)'))
    for i in range(len(skips) - 1):
        ch_ranges.append((skips[i], skips[i+1], f'Ch{i+1}'))

    for start, end, desc in ch_ranges:
        paths = analyzer.enumerate_paths(start, end)
        if paths:
            lines.append(f"    {desc:30s}: "
                         f"{paths[0]['cycles']:3d} - {paths[-1]['cycles']:3d} cyc")

    # Exit overhead (restore regs + RTI after last skip)
    exit_overhead = 0
    ei = analyzer.label_idx.get(skips[-1], 0)
    for i in range(ei, min(ei + 15, len(parsed))):
        info = parsed[i]
        if info and info.get('mnemonic'):
            exit_overhead += info['cycles']
            if info['is_return']:
                break

    lines.append(f"    {'Exit (restore + RTI)':30s}: {exit_overhead:3d} cyc")

    # Full handler: Tracker_IRQ → last skip + exit
    full_paths = analyzer.enumerate_paths('Tracker_IRQ', skips[-1])
    if full_paths:
        full_min = full_paths[0]['cycles'] + exit_overhead
        full_max = full_paths[-1]['cycles'] + exit_overhead

        lines.append(f"\n    FULL HANDLER: {full_min} - {full_max} cycles")

        # Identify common scenarios
        # Smallest = all channels inactive
        # Common fast = 4ch active, no boundary (2nd path per channel)
        lines.append(f"    All inactive:  {full_min} cycles")
        lines.append(f"    Worst case:    {full_max} cycles")

        # Page-cross potential
        pc_count = sum(1 for p in parsed if p and p.get('page_cross_possible'))
        if pc_count > 0:
            lines.append(f"\n    Note: {pc_count} instructions with potential "
                         f"+1 page-cross penalty")

        # Unresolved symbols
        ip = InstructionParser(parsed[0]['_symbols'] if parsed and parsed[0] and '_symbols' in parsed[0] else {})
        # Skip — we'll check this externally

        # CPU budget table
        lines.append(f"\n    CPU Budget (handler max = {full_max} cycles):")
        lines.append(f"\n    --- GR.0 Text Screen (avg 63% CPU efficiency) ---")
        lines.append(DmaModel.budget_table(full_min, full_max, 'gr0'))

        lines.append(f"\n    --- Blank Screen / DMA Off (92% CPU efficiency) ---")
        lines.append(DmaModel.budget_table(full_min, full_max, 'blank'))

    return '\n'.join(lines)


# ============================================================================
# ANNOTATED OUTPUT
# ============================================================================

def annotated_listing(parsed, source_info):
    """Annotated listing with cycle counts per instruction."""
    out = []
    section_total = 0
    section_label = None

    for i, info in enumerate(parsed):
        if info is None:
            continue
        raw = info.get('raw_line', '').rstrip()

        if info.get('label') and not info.get('mnemonic'):
            if section_label and section_total > 0:
                out.append(f";--- {section_label}: "
                           f"{section_total} cycles (fall-through) ---")
                out.append("")
            section_label = info['label']
            section_total = 0
            out.append(f"{'':20s}{raw}")
            continue

        cyc = info.get('cycles', 0)
        mn = info.get('mnemonic')

        if mn and cyc > 0:
            extra = ''
            if info.get('is_branch'):
                extra = f'/{info["cycles_taken"]}t'
            elif info.get('page_cross_possible'):
                extra = '/+1pc'
            tag = f"[{cyc}{extra}]"
            section_total += cyc
            out.append(f"{tag:>20s}{raw}")
        elif mn:
            out.append(f"{'[??]':>20s}{raw}")
        else:
            out.append(f"{'':20s}{raw}")

    if section_label and section_total > 0:
        out.append(f";--- {section_label}: "
                   f"{section_total} cycles (fall-through) ---")

    return '\n'.join(out)


# ============================================================================
# PROCESSING
# ============================================================================

def build_preprocessor(input_path, include_dirs, defines, pre_includes):
    """Build a preprocessor with pre-included files for symbol resolution."""
    pp = MadsPreprocessor(include_dirs=include_dirs, defines=defines)

    # Pre-include files first (for symbol resolution)
    for pi_path in pre_includes:
        resolved = None
        for d in [os.path.dirname(os.path.abspath(input_path))] + include_dirs:
            c = os.path.join(d, pi_path)
            if os.path.exists(c):
                resolved = c
                break
        if resolved is None and os.path.exists(pi_path):
            resolved = pi_path
        if resolved:
            pp.process_file(resolved)
            pp._included.discard(os.path.abspath(resolved))  # allow re-include
        else:
            pp.warnings.append(f"Pre-include not found: {pi_path}")

    return pp


def process_config(input_path, include_dirs, defines, pre_includes):
    """Process one configuration. Returns (pp, source_lines, parsed)."""
    pp = build_preprocessor(input_path, include_dirs, defines, pre_includes)
    source_lines = pp.process_file(input_path)
    ip = InstructionParser(pp.symbols)
    parsed = [ip.parse_line(l[0]) for l in source_lines]

    # Check for unresolved symbols
    if ip.unresolved:
        pp.warnings.append(
            f"Unresolved symbols (defaulting to abs): "
            f"{', '.join(sorted(ip.unresolved))}")

    return pp, source_lines, parsed


# ============================================================================
# MAIN
# ============================================================================

def main():
    ap = argparse.ArgumentParser(
        description='6502 Cycle Analyzer for MADS assembly',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
IMPORTANT: For accurate cycle counts, all zero-page symbols must be
resolved. Either process the top-level song_player.asm (recommended)
or use -P to pre-include zeropage.inc and atari.inc.

Examples:
  # Full analysis via top-level file (recommended):
  %(prog)s asm/song_player.asm -I asm \\
      -D TRACKER=1 OPTIMIZE_SPEED=1 MULTI_SAMPLE=1 PITCH_CONTROL=1 \\
         ALGO_FIXED=1 MIN_VECTOR=8 IRQ_MASK=1 VOLUME_CONTROL=1 \\
         BLANK_SCREEN=0 KEY_CONTROL=0 AUDCTL_VAL=0

  # Standalone with pre-includes:
  %(prog)s asm/tracker/tracker_irq_speed.asm -I asm \\
      -P common/zeropage.inc -P common/atari.inc \\
      -D TRACKER=1 VOLUME_CONTROL=1 MIN_VECTOR=8 IRQ_MASK=1

  # Compare all configs:
  %(prog)s asm/song_player.asm -I asm <defines> --all-configs
        """)

    ap.add_argument('input', help='Input .asm file')
    ap.add_argument('-D', '--define', nargs='*', default=[],
                    help='Definitions: NAME=VALUE ...')
    ap.add_argument('-I', '--include-dir', nargs='*', default=[],
                    help='Include search directories')
    ap.add_argument('-P', '--pre-include', nargs='*', default=[],
                    help='Pre-include files for symbol resolution '
                         '(e.g. zeropage.inc atari.inc)')
    ap.add_argument('-a', '--annotate', action='store_true',
                    help='Print annotated listing')
    ap.add_argument('-s', '--section', nargs=2, metavar=('START','END'),
                    action='append', default=[],
                    help='Analyze paths between labels')
    ap.add_argument('--summary', action='store_true', default=True,
                    help='Auto-detect IRQ handler summary')
    ap.add_argument('--all-configs', action='store_true',
                    help='Compare across VOLUME_CONTROL × MIN_VECTOR configs')

    args = ap.parse_args()

    # Parse defines
    defines = {}
    for d in args.define:
        if '=' in d:
            k, v = d.split('=', 1)
            try:
                defines[k.strip()] = int(v.strip(), 0)
            except ValueError:
                print(f"Warning: bad define: {d}", file=sys.stderr)
        else:
            defines[d.strip()] = 1

    input_dir = os.path.dirname(os.path.abspath(args.input))
    include_dirs = [input_dir] + [os.path.abspath(d) for d in args.include_dir]

    if args.all_configs:
        print(f"{'='*74}")
        print(f"  MULTI-CONFIGURATION COMPARISON")
        print(f"  File: {args.input}")
        print(f"{'='*74}\n")

        configs = []
        for vol in [0, 1]:
            for vec in [2, 4, 8, 16]:
                configs.append({'VOLUME_CONTROL': vol, 'MIN_VECTOR': vec})

        print(f"  {'VOL':>3s} {'VEC':>3s}  {'Min':>5s} {'Max':>5s}  "
              f"{'@5K avg':>7s} {'@6K avg':>7s} {'@6K wst':>7s}  {'Note':>6s}")
        print(f"  {'─'*3} {'─'*3}  {'─'*5} {'─'*5}  "
              f"{'─'*7} {'─'*7} {'─'*7}  {'─'*6}")

        for cfg in configs:
            merged = {**defines, **cfg}
            pp, src, parsed = process_config(
                args.input, include_dirs, merged, args.pre_include)

            labels = [p['label'] for p in parsed if p and p.get('label')]
            if 'Tracker_IRQ' not in labels:
                continue

            skips = sorted([l for l in labels if l.startswith('@skip_ch')])
            if not skips:
                continue

            analyzer = PathAnalyzer(parsed)
            paths = analyzer.enumerate_paths('Tracker_IRQ', skips[-1])
            if not paths:
                continue

            # Exit overhead
            exit_ov = 0
            ei = analyzer.label_idx.get(skips[-1], 0)
            for i in range(ei, min(ei + 15, len(parsed))):
                info = parsed[i]
                if info and info.get('mnemonic'):
                    exit_ov += info['cycles']
                    if info['is_return']:
                        break

            mn = paths[0]['cycles'] + exit_ov
            mx = paths[-1]['cycles'] + exit_ov

            avg_ratio = DmaModel.effective_ratio('gr0', 'average')
            worst_ratio = DmaModel.effective_ratio('gr0', 'worst')

            pct_5k_avg = mx / (1789773/5000 * avg_ratio) * 100
            pct_6k_avg = mx / (1789773/6000 * avg_ratio) * 100
            pct_6k_wst = mx / (1789773/6000 * worst_ratio) * 100

            note = "OK" if pct_6k_avg < 85 else ("TIGHT" if pct_6k_avg < 100 else "OVER")

            print(f"  {cfg['VOLUME_CONTROL']:3d} {cfg['MIN_VECTOR']:3d}  "
                  f"{mn:5d} {mx:5d}  "
                  f"{pct_5k_avg:5.1f}%  {pct_6k_avg:5.1f}%  {pct_6k_wst:5.0f}%  "
                  f"{note:>6s}")

        return

    # Single configuration
    pp, source_lines, parsed = process_config(
        args.input, include_dirs, defines, args.pre_include)

    if pp.warnings:
        print("--- Warnings ---", file=sys.stderr)
        for w in pp.warnings:
            print(f"  {w}", file=sys.stderr)
        print(file=sys.stderr)

    total_instr = sum(1 for p in parsed if p and p.get('mnemonic'))
    n_zp = sum(1 for k, v in pp.symbols.items() if isinstance(v, int) and 0 <= v <= 0xFF)
    n_abs = sum(1 for k, v in pp.symbols.items() if isinstance(v, int) and v > 0xFF)

    print(f"Processed: {len(source_lines)} lines, {total_instr} instructions")
    print(f"Symbols: {len(pp.symbols)} total ({n_zp} zero-page, {n_abs} absolute)")
    cfg_str = ', '.join(f"{k}={v}" for k, v in defines.items())
    print(f"Config: {cfg_str or '(none)'}")

    if args.annotate:
        print()
        print(annotated_listing(parsed, source_lines))

    for start, end in args.section:
        analyzer = PathAnalyzer(parsed)
        paths = analyzer.enumerate_paths(start, end)
        print(f"\n  Section: {start} -> {end}")
        if not paths:
            print("    No paths found.")
            continue
        for pi, p in enumerate(paths):
            taken = [k for k, v in p['choices'].items() if v]
            desc = ', '.join(taken) if taken else '(all fall-through)'
            print(f"\n    Path {pi+1}: {p['cycles']} cycles  [{desc}]")
            for d, c in p['trace']:
                print(f"      {c:2d}  {d}")
        print(f"\n    Range: {paths[0]['cycles']} - {paths[-1]['cycles']} cycles")

    if args.summary and not args.section:
        print(f"\n{'='*74}")
        print(f"  IRQ HANDLER CYCLE ANALYSIS")
        print(f"{'='*74}")
        print(irq_summary(parsed, defines))


if __name__ == '__main__':
    main()
