# POKEY VQ Tracker Beta 4

New beta is up. Main theme this round: making MOD import actually usable for real songs, and fixing the memory math so you know what fits before you build.

## MOD Import Wizard

The old import dialog had two checkboxes. The new one is a proper wizard that tells you whether your song will fit before you commit.

You pick the target machine (64 KB through 1088 KB with extended RAM banking), and the wizard shows a live memory budget. Toggle volume control on/off and watch the estimated data size update instantly — volume-on creates per-position patterns which can blow up fast on longer songs. The wizard shows the pattern count both ways and warns you when you're over budget.

Looped instruments now have a per-instrument table showing how many repeats each one needs and the resulting sample size. You can cap the max repeats globally (1–64) to keep things under control. That pad_sustain sample that wanted 52 repeats and 228 KB? Cap it at 8 and it's 35 KB.

Pattern deduplication runs automatically. When volume control is on, the importer creates one set of 4 patterns per song position — but many positions play the same MOD pattern with the same volume state, so the patterns end up byte-identical. Dedup hashes them and merges duplicates. Typical result: 240 patterns down to ~100. Often enough to fit banking mode's 10 KB data region.

If it still doesn't fit, the wizard shows a truncation option with a suggested position count.

## Volume Events (V--)

New event type that changes a channel's volume without retriggering the note. The MOD importer generates these from volume slides and set-volume effects. You can also enter them manually: press tilde (~) in the note column, or just type a volume value on an empty row — V-- is inserted automatically.

## Extended Memory Banking (128 KB – 1 MB)

Full bank-switched sample storage. Samples live in 16 KB banks at $4000–$7FFF, switched inline in the IRQ handler. A sample larger than 16 KB spans consecutive banks with automatic boundary crossing. RAM detection, multi-segment XEX generation, and banking-aware optimization all work.

Machine configs: 64 KB (no banking), 128 KB (130XE), 320 KB, 576 KB (Rambo/Compy), 1088 KB (1 MB expansion).

## IRQ Player Improvements

- RAW pitch accumulator rewritten: 62% CPU usage on 4 active RAW channels, down from 88%. 149 extra cycles of headroom per IRQ.
- Fixed 4-channel simultaneous note trigger stutter. The old commit phase held interrupts disabled for 604 cycles (IRQ period is 392). Now it's 44 cycles.
- AUDC volume mode bit pre-baked into sample data at conversion time, saving 8 cycles/IRQ.

## Other

- Cell color palettes — color notes, instruments, volume, and pattern numbers independently. 4 multi-color palettes (Chromatic, Pastel, Neon, Warm) with 16 colors each, plus uniform palettes (White, Green, Amber, Cyan, Blue, Pink). Pattern colors apply everywhere: Song grid, editor header combos, pattern/instrument selectors. Live palette preview in Settings. Default is Chromatic for everything.
- VU meters — vertical bars in SONG INFO panel, one per channel. Bars spike up on note trigger and decay down. Colored to match channel headers.
- Editor settings (hex mode, follow cursor, octave, step, palettes) are now personal — stored locally, not in .pvq files. Opening someone else's project won't change your preferences.
- Sustain effect in the sample editor — select a region, repeat it with crossfade. Good for extending short loops.
- Configurable start address ($0800–$3F00). Lower = more room for data.
- "Used Samples" checkbox — CONVERT/OPTIMIZE skip instruments not referenced in the song.
- Instrument export from the sample editor — WAV always, plus FLAC/OGG/MP3 if ffmpeg is available.
- Layout redesign: pattern editor is now full-height on the left. Settings moved to a modal.
- Build overflow diagnostics show per-file size breakdown when things don't fit.
- Effects indicator [E] in instrument list — click to open sample editor.
- Real-time CONVERT progress (was frozen until completion).

## Bug Fixes

Notable ones:

- OPTIMIZE was running on unprocessed sample data, ignoring Sustain/Trim effects entirely. A 15-second sustained sample was analyzed as 0.5 seconds.
- Double-sustain on .pvq round-trip: import applied sustain to audio AND stored it in effects chain, so save→load doubled the extension.
- song.speed and song.volume_control weren't persisted in .pvq files.
- Opening a .pvq overwrote hex mode, follow, octave, step with whatever the project had stored. Now all editor preferences stay local.
- Volume column not visible after MOD import or .pvq load even when volume control was enabled. Editor grid now syncs on any song change.
- Cross-platform keyboard fixes: PageUp/PageDown, F1-F3 octave, bracket keys now work on all DearPyGUI versions (1.x and 2.0). Added safe key constant resolution layer.
- Tilde (Shift+backtick) for V-- entry was always producing note-off instead. Fixed shift-state detection for the grave accent key.
- Banking shadow register conflict with PORTB on warm reset.

Full changelog in the download.

---

Still beta. Still experimental. The .pvq project format is stable — songs saved now will load in future versions. Feedback welcome, especially from anyone testing on real hardware with extended RAM.
