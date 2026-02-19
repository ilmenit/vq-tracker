# POKEY VQ Tracker - Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/).

---

## [Beta 5b] - 2025-02

### Multi-Channel Block Selection & Clipboard

- **2D block selection**: Selection now spans rows × channels as a
  rectangle. Previously selection was limited to a single channel column.
  Keyboard: Shift+Up/Down extends rows, Shift+Left/Right extends across
  channels (wraps at column boundaries). Shift+click on any cell extends
  the rectangle from cursor to clicked cell. Shift+click on row number
  selects that row range across all 4 channels.

- **Select All (Ctrl+A)**: Selects all rows across all channels in the
  current songline's patterns.

- **Multi-channel copy/cut/paste**: Ctrl+C/X copies the full 2D block.
  Ctrl+V pastes starting at the cursor position, clipping at channel and
  row boundaries. Delete/Backspace clears the entire selected block.

- **OS clipboard integration**: Uses `pyperclip` (new dependency) for
  reliable cross-platform clipboard access — Win32 API on Windows,
  pbcopy/pbpaste on macOS, xclip/xsel on Linux. Subprocess fallback
  retained for environments where pyperclip is unavailable.
  Copied blocks are written as human-readable tab-separated text
  (PVQT header, Note/Inst/Vol columns). Users can paste into Notepad,
  edit by hand, and paste back. Parser handles Windows BOM, CRLF line
  endings, garbage values, and caps at MAX_CHANNELS/MAX_ROWS to prevent
  memory bombs from malformed clipboard data.

### Shared Pattern Auto-Clone

- **Paste/cut/clear no longer leak to unrelated channels**: When a
  songline has multiple channels pointing to the same pattern (shared
  patterns), editing one channel would modify the other too. Now, before
  any destructive operation (paste, cut, clear-block), the tracker
  detects shared patterns and auto-clones them so only the target
  channels are affected. The non-target channel retains its original
  data. No clone occurs when patterns are already unique.

### Selection vs Beat Highlight

- **Selection color now takes priority over beat marker highlighting**:
  Previously, selected rows that fell on beat markers (every Nth row)
  showed the beat highlight color instead of the selection color, making
  it unclear which rows were selected. Fixed priority chain:
  cursor > playing > current_row > **selected** > inactive > highlight.

### Follow Mode Toggle

- **Follow mode checkbox + F4 shortcut**: A "Follow" checkbox is now
  visible in the pattern editor header bar. When enabled, the cursor
  chases the playback position. Press F4 or click the checkbox to toggle.
  State is persisted in the project file.

### Solo Buttons

- **Solo per channel (S buttons)**: Each channel header now has a small
  "S" button. Clicking it mutes all other channels (solo). Clicking
  again un-solos (enables all channels). Quickly switch solo between
  channels by clicking a different S button.

### WAV Export

- **File → Export WAV**: Renders the entire song offline to a 16-bit
  44.1 kHz mono WAV file. Plays through all songlines once. All channels
  are enabled during rendering regardless of current mute/solo state.
  Progress is reported in the status bar. 10-minute hard cap prevents
  runaway renders.

- **Auto-clone shared patterns on paste/cut/clear**: When pasting (or
  cutting/clearing) a multi-channel block, if a target channel's pattern
  is also used by a non-target channel in the same songline, the pattern
  is automatically cloned first. This prevents edits from "leaking" to
  channels outside the selection.

- **Selection highlight priority fix**: Selected cells now always show
  the selection color, even on beat-marker rows. Previously the beat
  highlight overrode the selection theme, making it invisible which rows
  were selected on every Nth row.

- **Keyboard blocked during modal dialogs**: Ctrl+A, Ctrl+C, and all
  other pattern-editor shortcuts are now blocked when any modal dialog
  is open (Build XEX, VQ Conversion, Settings, MOD Import, etc.).
  Previously these shortcuts leaked through to the pattern editor.

- **Build fix**: Fixed `UnboundLocalError: use_banking` crash in
  `build_xex_sync` — the variable was used before assignment when
  banking mode was referenced for song data export.

- **New module**: `clipboard_text.py` handles serialization/deserialization
  and cross-platform OS clipboard access.

- **68 new tests** covering 2D selection, multi-channel clipboard, text
  round-trips, error handling, shared-pattern auto-clone, and boundary
  clipping.

---

## [Beta 5a] - 2025-02

### Critical Fix — Audio stream silently dies after sample editor use

- **Root cause**: The sample editor and file browser used the high-level
  `sd.play()` / `sd.stop()` API (sounddevice) for waveform preview and
  file preview. This creates a **second** `OutputStream` on the same audio
  device. On many backends (Windows WASAPI exclusive mode, ALSA without
  PulseAudio, any configuration where concurrent streams contend for the
  device), opening a second stream — especially at a different sample rate
  (e.g. 15,720 Hz for POKEY-rate samples vs 44,100 Hz for the engine) —
  silently kills the main engine's callback stream. PortAudio stops
  invoking the callback, but `stream.active` may still report True. Result:
  permanent silence in the pattern editor and song playback until restart.

  **Fix**: Eliminated **all** `sd.play()` and `sd.stop()` calls from the
  codebase. Added a dedicated preview channel to `AudioEngine` that plays
  through the same single `OutputStream`. Sample editor waveform preview,
  range preview, original-audio preview, and file browser audio preview
  all now route through `AudioEngine.play_preview()`. The cursor thread
  reads position from the engine instead of wall-clock time. No second
  stream is ever created.

  Files changed: `audio_engine.py`, `sample_editor/ui_editor.py`,
  `ui_browser.py`

### Audio Engine Hardening

- **Exception-safe audio callback**: The `_audio_callback` is now wrapped
  in try/except. Previously, any transient error (numpy shape mismatch,
  threading race, etc.) would cause an unhandled exception that makes
  PortAudio permanently stop calling the callback. Now errors output
  silence for that buffer and log the error — the stream stays alive.

- **Stream health monitoring**: Added `ensure_stream()` method, called
  every ~2 seconds from the main loop. Checks `stream.active` and
  restarts the stream if it died (e.g. audio device disconnected/changed,
  OS-level reconfiguration). `start()` now detects and replaces dead
  streams instead of silently refusing when `self.running` is True.

- **Engine shutdown cleans up preview**: `stop()` now calls
  `stop_preview()` in addition to `stop_playback()`, preventing stale
  preview data from persisting across stream restarts.

- **Graceful degradation when engine is down**: Sample editor and file
  browser check `state.audio.running` before attempting preview playback.
  If the engine isn't available, they skip silently (sample editor) or
  show an error status (browser) instead of spinning a dead cursor thread.

### Keyboard Improvements

- **Global playback shortcuts (F5–F8)**: Play Song, Play Pattern, Play
  From Cursor, and Stop now work **regardless** of focus state — from text
  inputs, modal dialogs, song editor, instrument panel, or sample editor.
  The bypass is restricted to F-keys only; if a user remaps a playback
  action to a letter key via keyboard.json, it still respects text input
  gates (prevents typing 'P' from starting playback).

- **Space as universal play/stop**: Space toggles play/stop from pattern
  editor, song editor, and instrument panel (when playing). In instrument
  panel when stopped, Space still previews the selected instrument.
  Blocked in text input fields, sample editor (where Space = play
  waveform), and modal dialogs (when stopped — Space CAN still stop
  playback during a modal).

- **Stale `input_active` recovery**: The `input_active` flag could get
  stuck when DPG's `deactivated_handler` missed events (e.g. window focus
  loss, dialog opening over text field). The keyboard handler now verifies
  that a text field is actually focused before honoring the flag. If no
  field is focused, the flag is cleared and the key is processed normally.

### VU Meter Fixes

- **VU on note preview**: `_trigger_note()` now sets `vu_level`, so VU
  meters respond to note entry in the pattern editor, piano key previews
  in the instrument panel, and note previews in the sample editor.
  Previously only song playback drove VU levels.

- **VU on preview_row**: Note-off and volume-change events during row
  preview now update VU levels (note-off → 0, vol-change → proportional).

- **Consistent MAX_VOLUME usage**: All VU level calculations now use the
  `MAX_VOLUME` constant instead of hardcoded `15.0`.

---

## [Beta 5] - 2025-02

### Critical Fixes

- **DBANK_TABLE ordering fix — banks were aliased on real hardware**: The
  PORTB bank-selection table had entries ordered so that the first 4 values
  ($E3,$C3,$A3,$83) all had PORTB bits 2,3 = 00 — selecting the **same
  physical bank** on a 130XE. All 4 bank loads would overwrite each other,
  leaving only the last bank's data intact. The player would read garbage
  from banks 0–2.

  **Root cause**: The old table iterated one bank per 64KB block instead of
  4 banks within each block. On a 130XE, only bits 2,3 select banks; bits
  5,6,7 are ignored. The old table varied bits 5,6,7 while keeping bits 2,3
  constant.

  **Fix**: DBANK_TABLE now follows the reference `detect_ext` procedure's
  block-grouped ordering. Each 64KB block contributes 4 entries with bits
  2,3 cycling through 00,01,10,11. Blocks are ordered highest-first (X=15→0)
  for SpartaDOS X compatibility. The first 4 entries ($E3,$E7,$EB,$EF) now
  select 4 **distinct** physical banks on any memory expansion.

  Fixed in both `bank_packer.py` (Python DBANK_TABLE) and `mem_detect.asm`
  (ASM dBANK / setpb routine). Tables verified to produce identical values.

- **mem_detect.asm rewritten — alias-aware bank detection**: The old
  detection probed each of 64 PORTB values individually with write/verify.
  This cannot detect aliases: on a 130XE, all 64 probes succeed because
  the RAM exists — it's just the same 4 physical banks under different
  addresses. Result: `mem_banks_found = 64` on a 130XE.

  Worse, `mem_validate` also used write/verify and could not detect that
  "bank 4" physically aliases "bank 0". A song requiring 8 banks would
  pass validation on a 4-bank 130XE, then silently corrupt during loading.

  **Fix**: Replaced with the reference `detect_ext` algorithm adapted for
  our needs. Detection operates at the 64KB block level (16 blocks, 4 banks
  each). Zeroes $4000 in all blocks, then checks each: if still zero, it's
  a new distinct block (aliased blocks share the same physical RAM and get
  marked simultaneously). Non-destructive: all probed bytes are saved and
  restored. `mem_validate` simplified to a count comparison since detection
  is now accurate.

- **PORTB bit 0 fix — OS ROM disabled during playback**: Fixed a critical bug
  where all extended memory bank PORTB values had bit 0 set (OS ROM visible).
  The Atari OS ROM overlays $C000–$CFFF and $D800–$FFFF. When the IRQ handler
  wrote these values to PORTB during bank-switched sample playback, any data
  residing above $C000 would be silently replaced by OS ROM bytes, producing
  audio corruption or silence. The bug existed in two places:

  - **`bank_packer.py`** (build-time): The DBANK_TABLE values flowed directly
    into SAMPLE_PORTB and SAMPLE_BANK_SEQ tables embedded in the XEX. These
    tables are read at IRQ rate by the player — every bank switch during
    playback used a PORTB value with OS ROM enabled. Fixed: all runtime PORTB
    values are now masked with `& 0xFE` before being written to the tables.
    XEX loader stubs (INI blocks) correctly keep bit 0=1, since the OS must
    be visible during the DOS loading phase.

  - **`mem_detect.asm`** (runtime detection): No longer applicable — the
    rewritten detection does not output per-bank PORTB values (the player
    uses compile-time SAMPLE_PORTB tables instead).

### Major Enhancement

- **Per-bank VQ codebooks — dramatically improved audio quality**: Replaced the
  single global codebook architecture with per-bank codebooks. Previously, all
  instruments shared one 256-entry codebook in main RAM. Now each 16KB bank
  stores its own codebook at $4000, trained via k-means specifically on that
  bank's audio content.

  **Why this matters**: With a global codebook, 256 entries must represent every
  sound across all instruments — drums, bass, pads, silence — all competing for
  the same slots. K-means compromises everywhere. A kick drum's transient shares
  a codebook entry with a quiet pad, so both are slightly wrong.

  With per-bank codebooks, each bank gets 256 entries trained only on its own
  audio. A bank holding bass gets 256 bass-optimized patterns. A bank with
  hi-hats gets patterns optimized for high-frequency content.

  **Architecture changes**:
  - `tracker_irq_banked.asm`: New `BANK_DATA_HI` constant replaces hardcoded
    `$40` in all 12 bank-wrap points. Codebook size = 256 × MIN_VECTOR bytes.
  - `song_player.asm`: VQ_BLOB.asm excluded from banking mode assembly (saves
    ~1KB main RAM). VQ_LO/VQ_HI tables now point to $4000+ (bank-local
    codebook) instead of $8000+ (global blob in main RAM).
  - `build.py`: Per-bank re-encoding pipeline. Parses global VQ_BLOB, splits
    index streams by bank, trains bank-specific codebook via k-means (with
    adaptive silence reservation at index 0), re-encodes all indices.
    Generates banking-mode VQ_LO/VQ_HI and prepends codebook to each
    BANK_DATA_N.asm file.
  - `bank_packer.py`: `codebook_size` parameter now actively wired through
    the build pipeline.

  **Overhead**: 3–25% of each bank depending on vector size:
  - vec_size=2: 512B codebook (3.1%)
  - vec_size=4: 1024B codebook (6.2%)
  - vec_size=8: 2048B codebook (12.5%)

  **Silence handling**: Each bank's codebook independently detects near-silent
  vectors and reserves entry 0 for perfect silence when needed. Banks with
  only loud content use all 256 entries — no waste.

  **IRQ compatibility**: No changes to IRQ cycle budget. The codebook and index
  stream share the same $4000–$7FFF bank window. VQ_LO/VQ_HI lookup tables
  remain in main RAM ($8000+), always accessible.

### Tests

- Added `TestDBANKTable` (6 tests): verifies first 4/16/64 entries select
  distinct physical banks on 130XE/320k/1088k RAMBO, bit 4 always zero,
  bit 0 always one, exact match against reference `setpb` procedure.
- **Bank packer test suite updated**: Two existing tests that expected raw
  DBANK_TABLE values now correctly expect bit 0 cleared values. Added a
  dedicated regression test (`test_portb_bit0_cleared_for_runtime`) that
  verifies all runtime PORTB values — both per-instrument placements and the
  flattened `bank_seq` table — have bit 0 = 0.
- Added `TestPerBankCodebook` (7 tests): codebook space reservation, end
  address calculation, PORTB bit 0 correctness with codebooks, overflow
  detection.
- Added `TestPerBankVQReEncoding` (6 tests): VQ_BLOB parsing (with inline
  comment handling), re-encoding with AUDC mask preservation, silence
  reservation, VQ_LO/VQ_HI table generation, multi-instrument same-bank
  ordering.
- All 281 tests pass.

### Housekeeping

- **Banked IRQ handler macro refactor**: Replaced 852 lines of 4× hand-unrolled
  channel code with a single `CHANNEL_IRQ` macro (315 lines total). MADS `:1`
  parameter substitution generates all channel-specific labels (`ch0_bank`,
  `ch1_vq_pitch`, `trk2_stream_ptr`, etc.) from the channel number parameter.
  4 invocations: `CHANNEL_IRQ 0, AUDC1` through `CHANNEL_IRQ 3, AUDC4`.
  Generated code is identical; single point of maintenance for all channels.

- **Bank window exit checks optimized**: Eliminated all 12 `CMP #$80` / `BCC`
  / `BCS` patterns in the banked IRQ. The bank window is $4000–$7FFF, so any
  high byte >= $80 means we've exited. Since `INC` and `LDA` both set the N
  flag (bit 7 of result), `BPL` / `BMI` can replace the explicit compare:
  - VQ paths (8×): `INC ptr+1 / LDA ptr+1 / CMP #$80 / BCC` →
    `INC ptr+1 / BPL` (saves 4 bytes + 5 cycles each; `LDA` is redundant
    after `INC` because `INC` sets N)
  - RAW paths (4×): `LDA ptr+1 / CMP #$80 / BCS` →
    `LDA ptr+1 / BMI` (saves 2 bytes + 2 cycles each; `LDA` needed for
    end-of-stream check below)
  Total: 40 bytes saved, 48 cycles saved on bank-crossing paths.

- **Line endings normalized to LF**: All Python and ASM source files converted
  from CRLF (Windows) to LF (Unix) for consistent cross-platform behavior and
  cleaner diffs.

---

## [Beta 4] - 2025-02

### Features

- **MOD Import Wizard**: The import dialog is now a full wizard with live memory
  budget estimation. New features:

  - **Target machine selection**: Choose memory config (64 KB to 1088 KB) before
    import. The wizard shows how much space is available for song data vs samples
    and updates in real-time as you change options.

  - **Per-row volume control**: Faithfully imports volume slides and set-volume
    effects using per-position patterns with volume simulation. The wizard shows
    the estimated pattern count and data size for both ON and OFF.

  - **Extend looped instruments**: Unrolls loop regions using Sustain effect.
    Now includes a max repeats control (1–64) and a per-instrument table showing
    name, calculated repeats, and resulting size — so you can spot memory-hungry
    instruments and cap them.

  - **Pattern deduplication**: Automatically merges identical patterns after
    import, which is especially effective when volume control creates per-position
    patterns. Typical reduction: 40–60% fewer patterns.

  - **Song truncation**: When song data overflows, the wizard shows an
    Adjustments section with the option to keep only the first N positions.

  - **Live budget bar**: Shows estimated song data vs available space with
    percentage and fit/overflow status, updating instantly as options change.

- **Instrument Export**: The Sample Editor now has an Export button in the bottom
  bar. Exports the processed audio (with all effects applied) to WAV, and
  additionally to FLAC, OGG, or MP3 when ffmpeg is available. Uses the native
  save dialog with format filters.

- **Cell color palettes**: Pattern editor cells can be colored by note pitch,
  instrument number, volume level, or pattern number. Four multi-color palettes
  (Chromatic, Pastel, Neon, Warm) provide 16 distinct colors each, plus six
  single-color palettes (White, Green, Amber, Cyan, Blue, Pink). Each column
  has an independent palette selector in Editor → Settings, with a live preview
  strip showing all 16 colors. Pattern coloring applies everywhere pattern
  numbers appear: Song grid cells, per-channel pattern combos in the editor
  header, the Pattern section selector, and the instrument selector combo.
  Default palette is Chromatic for all columns. Settings are stored in the
  local editor config, not in .pvq project files.

- **VU meters**: Four vertical bars in the SONG INFO panel show per-channel
  activity during playback. Each bar spikes up on note trigger (height
  proportional to volume) and decays smoothly downward. Color-coded to
  match channel headers (red/green/blue/amber) with bright peak caps and
  subtle glow. Zero CPU cost when silent (drawing skipped entirely).

- **Volume-change events (V--)**: New event type that changes a channel's
  volume without interrupting the currently playing note. Displayed as "V--" in
  the pattern editor. Two ways to enter manually: press **~** (tilde) in the
  note column to insert V-- with the current brush volume, or simply type a
  volume value in the volume column on an empty row — V-- is inserted
  automatically. Also generated by the MOD importer when volume control is
  enabled. Requires Vol checkbox to be enabled in Song Info.

- **Sustain effect in instrument editor**: Select a region of a sample
  (left-click = start, right-click = end markers) and repeat it 1–64 times with
  optional crossfade smoothing (0–500 ms). Useful for extending short samples
  into longer sustained notes. Available in the Edit toolbar group.

- **"Used Samples" optimization checkbox**: Limits CONVERT and OPTIMIZE to only
  process instruments actually referenced in the song. Unused instruments are
  skipped during conversion and excluded from the memory budget. The optimizer
  shows a gray "–" next to unused instruments.

- **Configurable Start Address**: Set the player's ORG address ($0800–$3F00)
  in Song Info. Lower values give more room for sample data. Default $2000.

- **Memory Target selector**: Choose target memory configuration in Song Info:
  64KB (no banking), 128KB (130XE), 320KB, 576KB, 1088KB. Extended memory modes
  use bank-switched sample storage.

- **$C000 boundary check**: Assembly build now fails with a clear error if
  code and data exceed the $C000 OS boundary. The build error dialog shows
  available KB and suggests fixes.

- **Extended memory banking (128KB–1MB)**: Full bank-switched sample storage for
  Atari XL/XE extended RAM. Samples are stored in 16KB banks at $4000–$7FFF,
  switched inline in the IRQ handler. Multi-bank samples >16KB span consecutive
  banks with automatic boundary crossing. Includes RAM detection, multi-segment
  XEX generation, and banking-aware optimization.

### Interface

- **Redesigned main layout — Pattern Editor is now the primary panel**: The
  pattern editor spans the full window height on the left side, giving
  significantly more visible rows for editing (~19 rows at default window size,
  up from ~11). The Song grid, Pattern controls, and Song Info are on the right
  side, with the Instruments panel below them.

- **Settings moved to Editor menu**: Settings (Hex mode, Auto-save, Piano keys,
  Coupled entry) are now accessed via Editor → Settings in the menu bar, opening
  in a modal dialog. This frees up screen space for the pattern editor. All
  editor settings (including cell color palettes) are stored in the local config
  file, not in .pvq project files — so your preferences follow you across
  projects.

- **Mark interval moved to Current section**: The row highlight interval
  selector is now in the CURRENT toolbar alongside Instrument, Volume, Octave,
  and Step — always visible without opening the settings.

- **Real-time CONVERT progress**: The VQ conversion log window now streams
  output line-by-line as the encoder runs, showing iteration progress
  (e.g. "Iteration 12/50...") in real time. Previously output only appeared
  after the entire conversion finished, making it look like the program hung.

- **Effects indicator [E] in instrument list**: Each instrument row now shows
  an [E] button between the optimizer indicator and the instrument name. Blue
  when effects are applied (with tooltip listing effect types), blank otherwise.
  Clicking opens the Sample Editor for that instrument.

- **Detailed BUILD overflow diagnostics**: When song data exceeds the available
  memory region, the build log now shows a per-file breakdown with sizes and
  percentages (e.g. "SONG_DATA.asm: 20,620 bytes (20KB) — 77%"). The pre-flight
  check now runs for banking mode too (previously only 64KB mode), catching
  overflows before invoking MADS. ASM error messages now pinpoint which section
  caused the overflow.

### Performance

- **Optimized IRQ player for RAW samples**: The pitch accumulator for RAW
  (uncompressed) samples has been rewritten to combine two separate addition
  stages into one. For 4 active RAW channels, the player now uses 243 of 392
  available CPU cycles (62%) — down from 345 (88%) previously. This frees up
  149 cycles of headroom per IRQ, enough to comfortably handle occasional page
  crosses or additional processing.

- **Fixed audio stuttering on 4-channel note triggers**: When all 4 channels
  triggered simultaneously (common on the first rows of imported MODs), the
  commit phase ran with interrupts disabled for ~604 cycles — far exceeding the
  392-cycle IRQ period. This caused 1–2 missed IRQs and audible stuttering.
  Fixed by restructuring the commit into three phases: deactivate channels
  (no IRQ blackout needed), set up all data (IRQs fire normally, inactive
  channels are skipped), then briefly re-activate (44 cycles with IRQs
  disabled — down from 604).

- **Pre-baked AUDC volume mode bit**: The POKEY "volume-only mode" flag ($10)
  is now pre-baked into sample data at conversion time, removing one instruction
  from the IRQ hot path. Saves 8 CPU cycles per IRQ across 4 channels.

### Bug Fixes

- **OPTIMIZE ignored sample effects (Sustain, Trim, etc.)**: The optimizer
  used a lazy cache that was cleared whenever effects changed, silently falling
  back to the original unprocessed sample data. A Sustain-extended 15-second
  sample would be analyzed as its original 0.5-second length. Now the optimizer
  explicitly runs the effects pipeline before computing sizes and durations.

- **MOD patterns with Dxx/Bxx played silent tails instead of correct length**:
  Pattern break effects now correctly set the pattern length and trim rows.
  Backward position jumps (song loops) truncate the songline list.

- **Banking system shadow register conflicts**: The extended memory detection
  routine now saves and restores PORTB properly, preventing conflicts with
  the OS shadow register on warm resets.

- **Fixed stale text encoding table comment**: Corrected an outdated comment
  that referenced an old encoding format.

- **Removed dead code**: Cleaned up unused `original_sample_path` field,
  duplicate builder files, and an unused export function from the codebase.

- **Double-sustain on .pvq round-trip**: MOD import overwrote `sample_data`
  with the sustain-extended audio while also storing Sustain in the effects
  chain. After save→load, the pipeline re-applied Sustain to already-extended
  audio, doubling the loop unroll. Now the original audio stays in `sample_data`
  (saved to WAV in .pvq) and the extended version goes to `processed_data`
  (regenerated by the pipeline on load).

- **song.speed not serialized in .pvq**: The initial speed (from the MOD's
  first Fxx command) was lost on save→load, reverting to the default (6).
  Now stored in project.json `meta.speed`.

- **song.volume_control not set on import**: The wizard's "Enable per-row
  volume control" option created volume events in patterns but never set
  `song.volume_control = True`. BUILD would generate ASM without the
  VOLUME_CONTROL flag, so all V-- events were silently ignored by the player.

- **Import wizard crash with no loops**: Clicking Import on a MOD with no
  looped samples crashed because `on_import` read the max_repeats widget
  unconditionally. Now guarded with `does_item_exist()`.

- **Editor preferences overwritten by .pvq load**: Opening a project file
  overwrote hex mode, follow-cursor, octave, and step size with whatever
  was stored in the project. These are now personal settings that persist
  across projects via the local config file and are never changed by loading
  a .pvq.

- **Volume column not shown after MOD import or .pvq load**: Importing a MOD
  with volume control enabled (or loading a .pvq saved with volume on) did
  not rebuild the pattern editor grid. The Vol checkbox appeared checked but
  the volume column was invisible. Now the editor grid is rebuilt whenever
  a song is loaded, imported, or reset — syncing columns with the song's
  volume_control setting.

- **Key handling: cross-platform DPG compatibility**: DearPyGUI key constants
  changed between versions (1.x used GLFW codes, 2.0 uses ImGui enum). Added
  `dpg_keys.py` abstraction layer that tries multiple attribute names for
  version-dependent keys (Prior/PageUp, Next/PageDown, Back/Backspace,
  Open_Brace/LeftBracket, NumPadEnter/KeypadEnter, Grave/GraveAccent).
  Fixes PageUp/PageDown, F1-F3 octave selection, and bracket keys across
  all DPG versions. KEY_MAP is now built at runtime from resolved constants.

- **Tilde key (V-- entry) not working**: Pressing Shift+\` always entered
  note-off instead of V-- because DPG sends the same key code for both \`
  and ~. The keyboard handler now detects shift state and transforms the
  grave character to tilde before passing to handle_char().

---

## [Beta 3] - 2025-02

### Major Features

- **4-channel polyphonic playback**: Expanded from 3 to 4 independent sample
  channels. All four POKEY audio registers (AUDC1–AUDC4) are now used, giving
  the full hardware polyphony. The 6502 IRQ handler, process_row commit logic,
  and tracker_api all handle 4 channels with complete VQ/RAW mode support.

- **Mixed VQ + RAW sample encoding**: Instruments can now individually use either
  VQ (Vector Quantization) or RAW (uncompressed 4-bit PCM) encoding. VQ gives
  better compression (8:1 with vec_size=8) using a shared 256-entry codebook.
  RAW uses more memory but costs fewer CPU cycles per sample — no codebook
  lookup needed. The player selects the correct handler per channel at note
  trigger time via self-modifying code, with zero overhead during playback.

- **OPTIMIZE button**: Analyzes all instruments and the song arrangement to
  recommend VQ or RAW mode for each instrument. The optimizer simulates
  playback row-by-row to find the worst-case CPU load, then switches short
  or CPU-heavy instruments to RAW when memory allows. After optimization,
  V (VQ) and R (RAW) indicators appear next to each instrument showing the
  recommendation. Toggling an instrument's checkbox preserves these indicators.

- **Amiga MOD import**: Import 4-channel ProTracker .MOD files with automatic
  conversion of patterns, instruments, song arrangement, and speed settings.
  MOD samples are resampled to the POKEY rate and their `base_note` is set to
  C-3 (matching MOD tuning conventions). After import, the optimizer runs
  automatically to assign RAW/VQ modes.

- **Configurable memory limit**: The sample data memory budget is adjustable
  (default 35 KB). The OPTIMIZE button and BUILD process respect this limit
  when deciding how to fit instruments into the Atari's 64 KB RAM.

- **Coupled note entry mode**: New setting (on by default) that controls whether
  entering a note on an occupied cell overwrites the instrument and volume
  (FastTracker 2 style) or preserves them (Renoise-style edit mask). Toggle
  in Settings panel.

- **Clone instrument**: Deep-copies the selected instrument (audio data, effects
  chain, settings) to a new slot at the end of the instrument list.

### Bug Fixes

- **MOD instruments played 2 octaves too high on Atari**: The ASM pitch table
  ignored `base_note`. MOD samples are pitched for C-3 playback, but the
  exporter mapped C-3 to pitch index 24 = 4.0x instead of 1.0x. Fixed by
  extending the pitch table from 36 to 60 entries (5 octaves including 0.25x
  and 0.5x sub-octaves) and applying a base_note correction during export:
  `export_note = gui_note + 24 - (base_note - 1)`.

- **VQ preview cheating vs RAW**: The VQ preview played codebook vectors at
  float32 precision (~24-bit quality) instead of quantizing through the real
  16-level POKEY voltage table. This made VQ sound dramatically better than RAW
  in preview, but the difference does not exist on real hardware. Both VQ and
  RAW previews now go through honest 16-level POKEY quantization.

- **RAW preview used wrong interpolation**: RAW preview used sinc interpolation
  (scipy.signal.resample) creating ringing artifacts. Now uses zero-order hold
  (np.repeat at 1.77 MHz → resample to 48 kHz), matching real POKEY hardware
  sample-and-hold behavior and identical to the VQ preview method.

- **IRQ skip labels fell through into RAW handlers**: Every `chN_skip` label
  in tracker_irq_speed.asm pointed to the same address as `chN_raw_boundary`
  (only comments between, no instructions). On every non-boundary tick, execution
  fell through from skip into the RAW boundary handler. Fixed by placing all RAW
  handlers after the `rti` instruction, reachable only via SMC JMP targets.

- **Branch out of range after removing size optimization**: Removing
  OPTIMIZE_SPEED conditionals made commit blocks exceed the 6502's ±127 byte
  relative branch limit. Fixed by inverting `beq @commit_done_N` to
  `bne @do_commit_N / jmp @commit_done_N`.

- **Atari data size display excluded RAW samples**: The size shown after
  conversion only counted VQ_BLOB + VQ_INDICES. RAW_SAMPLES bytes were never
  added. All-RAW projects showed "2 B". Fixed.

- **Keyboard notes played while typing in Limit field**: The memory limit
  input field did not suppress keyboard note entry, causing notes to trigger
  while typing numbers. Fixed by adding the field to the input-active check list.

- **Optimize indicators disappeared on checkbox toggle**: Clicking a VQ/RAW
  checkbox cleared the optimize result, hiding the V/R recommendation
  indicators. The indicators now persist through checkbox toggles (only cleared
  by operations that change the instrument list or settings).

### Improvements

- **Noise shaping for RAW samples**: 1st-order error-feedback noise shaping
  pushes quantization noise from audible low frequencies to less-audible high
  frequencies. At 15 kHz POKEY rate, noise in the 0–2 kHz band drops by ~18x.
  Auto-enabled when POKEY rate ≥ 6 kHz.

- **2-cycle/channel IRQ optimization**: Data bytes now store raw 0–15 volumes
  instead of pre-baked `$10|vol`. Removes the `AND #$0F` instruction from the
  IRQ hot path, saving 8 cycles per IRQ tick across 4 channels.

- **Removed size-optimized player from tracker**: The tracker now always uses
  the speed-optimized IRQ handler. The size-optimized variant (nibble-packed,
  no RAW support) remains available in the standalone vq_converter.

- **Auto-optimize on MOD import**: After importing a MOD file, the RAW/VQ
  optimizer runs automatically so instruments start with sensible mode
  assignments.

- **Simplified menus**: Removed "Import vq_converter..." and "Export .ASM..."
  menu items. The tracker workflow is now: compose → convert → build (.xex).

### Documentation

- Updated User Guide: 4-channel playback, VQ vs RAW encoding explained,
  OPTIMIZE workflow, MOD import guide, memory limit configuration.

---

## [Beta 2] - 2025-02

### Bug Fixes

- **Windows: WinError 32 when loading .pvq files**: Loading projects failed with
  "The process cannot access the file because it is being used by another process".
  Root cause: ZIP archives use forward slashes (`samples/00.wav`) but Windows uses
  backslashes. When checking if source and destination paths were the same,
  string comparison failed due to mixed separators, causing `shutil.copy2()` to
  attempt copying a file onto itself. Fixed with `os.path.normpath()` before
  path comparison. (`file_io.py`)
- **Linux/macOS: FFmpeg not found for MP3 import**: The `_setup_ffmpeg_for_pydub()`
  function only set up the bundled FFmpeg path on Windows. Now works on all
  platforms, enabling MP3/OGG/FLAC import from both source and PyInstaller builds.
  (`main.py`)
- **Misleading VQ conversion size**: The size shown after conversion (~30KB) didn't match
  the actual .xex size (~7KB). The encoder's estimated size didn't account for nibble
  packing. Fixed by having `MADSExporter.export()` return the actual byte count after
  export, which `builder.py` now stores in `conversion_info.json`. (`vq_converter/`:
  `mads_exporter.py`, `builder.py`; tracker: `vq_convert.py`, `ui_callbacks.py`,
  `ui_refresh.py`)
- **Song editor undo not recorded**: Editing pattern assignments or speed
  values in the song editor via keyboard did not create an undo snapshot.
  Changes were silently permanent. (`keyboard.py`: added `save_undo("Edit song")`
  before `_apply_song_pattern_value` commits)
- **Autosave lost VQ settings**: The `vq_enhance` and `vq_optimize_speed`
  fields were not included in the `EditorState` written by autosave, causing
  these settings to reset to defaults when restoring from an autosave.
  (`ui_globals.py`: added both fields to the autosave `EditorState` constructor)

### Project File Format

- **Simplified and portable .pvq format**: Complete redesign of sample storage:
  - Samples stored as numbered files: `samples/000.wav`, `samples/001.wav`, etc.
  - No paths stored in JSON — sample existence determined by file presence
  - Removed `sample_path`, `original_sample_path`, `sample_file` from serialization
  - Instrument `name`, `base_note`, `sample_rate` are the only persisted fields
  - `sample_path` is now runtime-only, reconstructed on load
  - Changed numbering from `02d` to `03d` to support all 128 instruments
- **Cross-platform compatibility**: Project files now fully portable between
  Windows, macOS, and Linux without path separator issues

### Architecture

- **Operations module refactored into `ops/` package**: The monolithic
  `operations.py` (1181 lines) has been replaced by ten focused modules under
  `ops/`, grouped by domain: `base`, `file_ops`, `editing`, `navigation`,
  `playback`, `instrument_ops`, `pattern_ops`, `songline_ops`, `input_settings`.
  The `operations.py` wrapper has been removed; all call sites now
  `import ops` directly.
- **Typed UI callback interface**: Replaced ~15 mutable module-level callback
  variables with `UICallbacks`, a typed dataclass in the new
  `ui_callbacks_interface.py`. All callbacks have safe no-op defaults, so the
  operations layer works even before the UI is wired up. Callback wiring in
  `main.py` now constructs a single `UICallbacks` instance and passes it via
  `set_ui_callbacks()`.

### Code Quality

- **Bare `except:` clauses eliminated**: All bare `except:` and `except: pass`
  patterns replaced with specific exception types and diagnostic logging:
  - `file_io.py`: `OSError` for lock/unlock, `Exception` for fallback paths,
    `scipy`/`wave` read failures now logged at debug/warning level
  - `audio_engine.py`: stream close, callback errors now logged with context
  - `ui_globals.py`: parse errors narrowed to `ValueError`/`TypeError`,
    autosave cleanup errors logged
- **Magic numbers replaced with constants**: Hardcoded `6` (speed) and `64`
  (pattern length) in `audio_engine.py` replaced with `DEFAULT_SPEED` and
  `DEFAULT_LENGTH` from `constants.py`.
- **Removed unused code**:
  - `original_sample_path` field from `Instrument` dataclass
  - `is_converted` parameter from `load_sample()` function
  - `_safe_filename()` function (no longer needed with numbered samples)
  - Backward compatibility code for old project formats

### Testing

- **New test suite**: 86 unit tests across five modules, runnable via
  `run_tests.sh` / `run_tests.bat`:
  - `test_data_model.py` (37 tests): Song, Pattern, Row, Instrument
    creation, serialization round-trip, edge cases
  - `test_file_io.py` (19 tests): Safe filename generation, project
    save/load, format version handling, lock management
  - `test_state.py` (19 tests): UndoManager push/pop/redo, Clipboard,
    Selection, EditorState persistence
  - `test_export.py` (6 tests): Binary and ASM export validation,
    event encoding, note mapping
  - `test_ui_callbacks_interface.py` (5 tests): UICallbacks defaults,
    field assignment, mutation isolation

### File Changes Summary

New files: `ops/` (10 modules), `ui_callbacks_interface.py`, `tests/` (5 test
modules + runner scripts).
Removed: `operations.py`.
Modified: `keyboard.py`, `main.py`, `ui_globals.py`, `ui_callbacks.py`,
`ui_build.py`, `audio_engine.py`, `file_io.py`, `data_model.py`, `vq_convert.py`,
`ui_refresh.py`.
Unchanged: all ASM sources, `build.py`, `state.py`, `constants.py`, `runtime.py`,
`ui_theme.py`, `ui_browser.py`, `ui_dialogs.py`, `analyze.py`, `build_release.py`.

---

## [Beta 1] - 2025-02

### Initial Release

First public beta of POKEY VQ Tracker — an experimental sample-based music
tracker for Atari XL/XE computers using Vector Quantization audio compression.

### Core Features

- 3-channel polyphonic sample playback on stock 64K Atari XL/XE
- 3 octaves (36 semitones) with 8.8 fixed-point pitch calculation
- VQ compression with adjustable sample rate (3333–15834 Hz) and vector
  size (2, 4, 8, 16)
- Pattern-based sequencer with songline arrangement
- Real-time preview playback in the tracker
- One-click export to Atari executable (.xex) via integrated MADS assembler
- Multi-format sample import (WAV, MP3, OGG, FLAC, AIFF, M4A)
- Speed and size optimization modes for the 6502 IRQ handler
- Optional per-note volume control, display blanking, keyboard control

### Editor

- Piano and tracker keyboard modes for note entry
- Pattern copy/paste/transpose
- Undo/redo
- Hex/decimal display toggle
- Row highlighting and follow mode

### Project Management

- Self-contained `.pvq` project format (ZIP-based with embedded samples)
- Auto-save, recent files list, editor state preservation

### Build System

- Cross-platform builds (Windows, macOS, Linux) via PyInstaller
- Bundled MADS assembler binaries

### Analysis

- CPU cycle budget analysis with per-row cost estimation and configuration
  recommendations

### Known Issues (fixed in Beta 2)

- Windows: Loading .pvq files failed with WinError 32 due to path separator mismatch
- Linux/macOS: FFmpeg not found for MP3/OGG/FLAC import in bundled builds
- Project files not portable across platforms (absolute paths stored)
- VQ conversion showed misleading size (included preview WAVs, not just Atari data)
- Song editor keyboard edits did not record undo snapshots
- Autosave did not persist `vq_enhance` and `vq_optimize_speed` settings
- Bare `except:` clauses throughout the codebase silently swallowed errors
- Sample filenames limited to 99 instruments (used `02d` format)
- No unit tests

### Known Limitations

- Analysis provides estimates, not cycle-accurate emulation
- No effect commands (portamento, vibrato, etc.)
- Single codebook shared across all samples
- Base RAM only (no extended memory support)
- PAL timing is the primary focus; NTSC is less tested

---

## Future Plans

See `UserGuide.md` "Future Roadmap" section for planned features including
cycle-accurate emulation, extended memory support, multi-codebook compression,
effect commands, and more.

---

## Credits

- MADS Assembler by Tomasz Biela (Tebe)
- Altirra Emulator by Avery Lee
- DearPyGui by Jonathan Hoffstadt
- The Atari 8-bit community

---

*Thank you for trying POKEY VQ Tracker! Feedback and bug reports welcome.*
