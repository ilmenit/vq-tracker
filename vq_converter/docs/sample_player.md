# Sample Player Architecture

The `players/sample_player.asm` (PokeyVQ Sample Player) is an interactive Atari executable designed to play multiple VQ-compressed audio samples. It differs from the standard player by adding keyboard input handling, visual feedback, and multi-sample state management.

## 1. High-Level Overview

-   **Entry Point**: `ORG $2000` (standard).
-   **Configuration**: Requires `MULTI_SAMPLE = 1` in `VQ_CFG.asm`.
-   **Dependencies**: Uses `lib/vq_player.asm` as the audio engine but provides its own frontend logic.

### User Interface
-   **Visual**:
    -   Uses a custom **Display List** with ANTIC Mode 2 (Text).
    -   Displays instructions or (in Pitch Mode) status like Octave/Note.
    -   **Background Color**:
        -   **Black/Empty**: Initialization.
        -   **Orange ($20)**: Idle / Finished (Waiting for input).
        -   **Green ($40)**: Playing active sample.
        
-   **Input Modes**:
    1.  **Standard Mode** (`PITCH_CONTROL` undefined):
        -   Keys `A-Z` map to Samples 0-25.
        -   Pressing a key triggers `PokeyVQ_Init` for that sample index.
    2.  **Pitch Control Mode** (`PITCH_CONTROL` defined):
        -   **Samples**: Keys `Q` to `P` (Top row) select Samples 0-9.
        -   **Octave**: Keys `1` to `4` select Octave 0-3.
        -   **Notes**: Piano layout (Z,S,X,D,C,V,G,B,H,N,J,M) triggers playback.

---

## 2. Architecture & Execution Flow

### Initialization (`start`)
1.  **System Setup**: Disables IRQ/OS, enables RAM ($FE), sets up NMI/IRQ vectors.
2.  **Display**: Sets up Display List (`dlist`) and enables DMA/NMI.
3.  **Keyboard**: Initializes `SKCTL` (Debounce/Scan start).
4.  **State**: Clears `sample_finished`, `current_sample`, and pitch variables (if enabled).

### Main Loop (`main_loop`)
The loop polls the hardware keyboard state directly (bypassing OS).

1.  **Status LED (Background)**:
    -   Checks `sample_finished`.
    -   Sets `COLBK` (Background Color) to Orange (Idle) or Green (Playing).
2.  **Input Polling**:
    -   Reads `SKSTAT` (Bit 2) to detect key press.
    -   Reads `KBCODE` to get hardware key code.
3.  **Key Processing**:
    -   **Standard**: Scans `key_table` to match `KBCODE`. If match -> `PokeyVQ_Init(SampleIndex)`.
    -   **Pitch Mode**:
        -   Scans `sample_key_table`, `octave_key_table`, `white_key_table`, `black_key_table`.
        -   Updates state (`current_octave`, `current_semitone`, etc.).
        -   Updates Screen Text (`update_display`).
        -   Triggers internal `PokeyVQ_PlayNote` only if valid note/sample combo.

### Audio Integration
The `sample_player.asm` is the *Controller*. It "drives" the engine in `lib/vq_player.asm`.

-   **Triggering**:
    -   Calls `PokeyVQ_Init` (with Accumulator = Sample Index) to start a new sample.
    -   Calls `PokeyVQ_PlayNote` (Pitch Mode) to set pitch + init.
-   **Interrupts**:
    -   The actual audio playback happens in the background via `PokeyVQ_IRQ` (defined in `lib/vq_player.asm`).
    -   The main loop only handles UI and triggers.

---

## 3. Data Structures

### Tables
Lookup tables convert Hardware Key Codes (`KBCODE`) to logic values.

-   **Standard**:
    -   `key_table`: Maps A-Z code to 0-25.
-   **Pitch Mode**:
    -   `sample_key_table`: Q-P -> 0-9.
    -   `octave_key_table`: 1-4 -> 0-3.
    -   `white_key_table` / `black_key_table`: Base note offsets.
    -   `octave_base`: Multiplication table (Octave * 12).
    -   `note_names`: Screen codes for C, C#, D, etc.

### Variables
Additional state tracking in `sample_player.asm`:

-   `current_sample`: Currently selected/playing sample index.
-   `sample_finished`: Flag (read from `lib/vq_player.asm` usually set at $FF when done).
-   `playing_note` (Pitch Mode): Prevents re-triggering the same note (buzz fix).

---

## 4. Conditional Compilation

Like `player.asm`, `sample_player.asm` respects `VQ_CFG.asm`.

-   **`PITCH_CONTROL`**: Drastically changes `main_loop` from simple A-Z select to complex piano logic and enables `update_display`.
-   **`ALGO_RAW` vs `VQ`**: Handled transparently by `lib/vq_player.asm`, but `sample_player.asm` includes the correct data files (`RAW_DATA.asm` vs `VQ_*.asm`) at the end.

## 5. Memory Map & Display System

The sample player uses a unique memory layout where the screen memory is embedded within the code segment to avoid external dependencies.

| Segment | Location | Description |
|---------|----------|-------------|
| **Zero Page** | `$80` - `$9F` | Core pointers and state variables. |
| **Code** | `$2000` | **Screen Memory**: `text_to_print` buffer is defined *first*.<br>**Display List**: `dlist` definition follows immediately.<br>**Logic**: Main program code follows. |
| **Data** | Follows Code | Audio data (`VQ_BLOB`, etc.) is placed after the code segment. |

### Display List Logic
-   **Location**: Start of Code Segment (approx `$2000`).
-   **Structure**:
    -   24 Blank Lines (`$70` x 3) to center text.
    -   **LMS Instruction** (`$42`): Loads Memory Scan for Mode 2 (Text). Points to `text_to_print`.
    -   Blank Lines (padding).
    -   JVB (`$41`) loop.
-   **Screen Memory**: The `text_to_print` label points to ASCII/Internal code data defined directly in the assembly source (e.g., `dTA d"TEXT"`). This buffer **is** the screen memory. Changes to `text_to_print` via `update_display` are immediately reflected on screen.

*Note: `MULTI_SAMPLE=1` is mandatory, so `SAMPLE_DIR.asm` is included by `vq_player.asm`.*
