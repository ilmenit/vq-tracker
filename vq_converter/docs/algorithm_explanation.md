# Understanding the Audio Compression & Playback System

## Quick start

1. Select a piece of sound/music to convert (MP3, WAV).
2. The size/quality of generated file depends on the music length, play rate, selected quality, and other options. Generally, the longer the music, the worse quality.
3. If you get a message about too big size, lower quality or bit-rate.

## The Challenge
The Atari 8-bit computer (6502 CPU @ 1.77 MHz) has very limited resources compared to modern devices, typically 64KB total (with ~30-40KB available for data).

Storing raw audio (like a .WAV file) consumes massive amounts of space. Even at a very low quality (4kHz, 4-bit), one second of audio takes ~2KB. A 3-minute song would require ~360KB, far exceeding the memory capacity. To play long audio clips, we must **compress** the data significantly. Compressing RAW data is an option and there are players using LZSS or LZSA, but stronger compression algorithms are too slow for the Atari. 

## The Solution: Vector Quantization (VQ)

We use a technique called **Vector Quantization (VQ)**. Think of it like a "Paint by Numbers" kit or building with Lego blocks.

### How it works
1.  **The "Vectors" (Building Blocks):** Instead of storing every single sample of sound, we split the audio into tiny snippets called **vectors** (e.g., 8 samples long).
2.  **The "Codebook" (Palette):** We analyze the entire song and find the most common shapes or patterns of these vectors. We create a collection of the best 256 patterns. This collection is called the **Codebook**.
3.  **Encoding:** For every segment of the song, we don't save the sound itself. We just save the **Index Number** (0-255) of the pattern in the Codebook that sounds most like it.

---

## Design Decisions & Justifications

### 1. Variable Length Vectors
We don't use fixed-size blocks, instead we improved this by using **Variable Lengths** (e.g., 1 to 16 samples).

*   **Complexity:** Fast, changing sounds (drums, speech) need short vectors to capture details.
*   **Simplicity:** Long, steady sounds (silence, sustained notes) can be covered by one long vector.

**Benefit:** By using long vectors for simple parts, we save space. We only "spend" our precious bytes on the complex parts that need them.

### 2. 1-Byte Encoding
Our algorithms are limited to **256 indices** (0-255). We stick to max. 256 indices to maintain a **1-byte-per-vector** data stream, ensuring the file size is small enough to fit in RAM and the player is fast enough to run.

---

## The "Sliding Window" Algorithm

In case of codebook up to 256 patterns the longer the song, the worse quality. 
A strict limit of 256 patterns for an entire song can sound "muffled" because you can't capture every nuance of a 3-minute track with just 256 shapes.

To solve this without breaking the "1-byte limit", we use a **Sliding Window**.

### The Concept
Imagine a long tape of thousands of unique patterns. The Atari can't see the whole tape at once. It has a "Window" that can only see **256 patterns** at a time.
*   As the song takes place, we slowly **slide** this window forward.
*   Old patterns that aren't needed anymore fall off the left side.
*   New patterns for the upcoming section appear on the right side.

### The Sliding Window Strategy
To optimize for both size and quality, the encoder uses a **Linear Sliding Window**.

*   **Mechanism:** Uses a **Fixed Interval Counter** in the player.
*   **How it works:** The encoder calculates a perfect integer interval (e.g., "Slide every 30 vectors") based on the song length. The player counts down and slides simply by incrementing its internal pointers.
*   **Benefit:** Removes all `0xFF` command bytes from the stream, saving space and ensuring purely deterministic execution. The window slides linearly from the start of the codebook to the end over the duration of the song.

### Dual Channel Mode
*   **Mechanism:** Uses two POKEY channels for increased resolution.
*   **How it works:** By mixing two 4-bit channels (0-15 volume), we can achieve approximately 31 distinct voltage levels (~5-bit resolution).
*   **Benefit:** Reduces quantization noise and improves audio clarity compared to standard 4-bit playback.

### Speed vs. Size Optimization
*   **Optimization (--optimize):** Decouples data formatting from audio features.
    *   **Size (Standard):** Packs 2 samples into 1 byte. Smaller file size. Uses buffered register writes to maintain audio stability.
    *   **Speed (Fast):** Stores 2 bytes per sample (Interleaved) in codebook. Larger file size (approx 2x for codebook), but slightly faster CPU execution (direct fetch to registers).
    *   **Note:** Use `size` for longer songs to fit in RAM, or `speed` if you have plenty of RAM and want to save a few CPU cycles per interrupt.
 

---

## How the Music Player Works

The player running on the Atari is a piece of valid assembly code designed for speed.

### The Mechanism
1.  **Interrupt Driven:** The player runs on a timer interrupt (IRQ). It wakes up thousands of times per second (e.g. 4000Hz or 8000Hz) to update the sound hardware.
2.  **The Fetch Loop:**
    *   The player checks: *"Is the current vector finished playing?"*
    *   **No:** It grabs the next sample from the current vector and sends it to the hardware.
    *   **Yes:** It fetches the next **Index Byte** from the song data.
        *   It looks up the **Address** and **Length** of that pattern in the Codebook.
        *   It resets its counters and starts playing that new vector.

### Hardware "Hacks": The Dual Channel output
Standard Atari sound is 4-bit (16 volume levels), which is quite gritty.
To get better quality (approx 5-bit), we use **Two Channels** combined:
*   **Channels 1 & 2:** Both channels are summed together.
*   **Result:** This allows for 31 distinct voltage levels (0-30), reducing quantization noise significantly compared to the 16 levels of a single channel.

By mixing these two together (physically or via emulated features), we get much smoother audio than the hardware was originally designed to produce. The algorithm automatically splits the high-quality sound into these two components during encoding.

---

## Encoder Parameters

The `pokey_vq.cli` tool allows you to tune the compression and playback engine. Here is what each parameter does:

### General
*   `input_file`: The source audio file (MP3, WAV, etc.).
*   `-o`, `--output`: Optional. Explicitly name the output `.xex` file. If omitted, a structured folder is created in `outputs/`.
*   `-r`, `--rate` (Default: 7917): Target sample rate in Hz. The tool will automatically "snap" this to the nearest valid PAL POKEY divisor frequency.
    *   *Tip:* 7-8kHz is standard. ~15kHz is possible but uses more CPU.
*   `--channels` (Choices: `1`, `2`. Default: `2`):
    *   `1`: Single Channel. Uses 1 POKEY channel (4-bit). Smaller data/file size, lower quality.
    *   `2`: Dual Channel. Mixes 2 POKEY channels (approx 5-bit). Larger data size, better quality.
*   `-p`, `--player` (Default: `vq_basic`): Selects the player engine and playback behavior:
    *   `vq_basic`: Standard VQ player. Loops a single sample. Good for music loops.
    *   `vq_samples`: Multi-sample player. Plays different samples when A-Z keys are pressed.
    *   `vq_pitch`: Pitch-controlled player. Plays sample pitched on a piano keyboard.
    *   `vq_multi_channel`: Polyphonic tracker player. Supports 3 parallel channels triggered by 1-3 keys.
    *   `raw`: Uncompressed 8-bit stream. Loops one sample. Max quality but consumes huge memory (1KB per ~0.1s).
*   `--wav` (Default: `on`): Exports a verification `.wav` file. Useful to preview how the Atari will sound (simulated).

### Multi-Sample Support
You can pass multiple input files to create a single compilation (player or data).
*   **Method:** All samples are merged into a single stream.
*   **Requirement:** Any mode except `raw` and `vq_basic` (which typically only loop one file) works naturally with multi-sample inputs. `vq_samples` is designed for this.
*   **Result:** All samples share the same 256-entry codebook. This is efficient but means the codebook must be "generic" enough to cover all sounds in the compilation.

### Quality Tuning

*   `-q`, `--quality` (0-100, Default: 50): Controls the balance between "saving space" and "matching the sound".
    *   Higher values (e.g., 80-100) allow the encoder to pick vectors that match the audio better, even if they are "expensive" in terms of bitrate.
    *   Lower values (e.g., 0-30) force the encoder to prioritize efficiency.
*   `-s`, `--smoothness` (0-100, Default: 0): Enforces "temporal coherence".
    *   If the audio sounds "jittery" or too random, increase this. It penalizes the encoder for jumping wildly between very different vectors, producing a smoother (but potentially more muffled) sound.
*   `-c`, `--codebook` (Default: 256): The size of the palette. Max 256 for 8-bit players.
*   `-i`, `--iterations` (Default: 50): Max number of VQ iterations (training passes).
*   `-miv`, `--min-vector` (Default: 1): Minimum vector length.
*   `-mav`, `--max-vector` (Default: 16): Maximum vector length.
*   `-l`, `--lbg`: Uses the LBG (Linde-Buzo-Gray) algorithm with K-Means++ for initial codebook generation. Can improve quality.

### Advanced / Enhancements
*   `-e`, `--enhance` (Default: `on`): Applies a pre-processing chain:
    *   **High-Pass Filter (50Hz):** Removes inaudible rumble that wastes energy.
    *   **Soft Limiter:** Boosts the overall volume (loudness) without harsh digital clipping, crucial for 8-bit audio where dynamic range is low.
    *   **Normalization:** Maximizes the signal to fit the full range.
*   `-v`, `--voltage` (Default: `off`): "Constrained" mode. Force vectors to match exact POKEY voltage levels.
*   `-op`, `--optimize` (Choices: `size`, `speed`. Default: `size`):
    *   **Size**: Uses standard "Packed" format (1 byte per sample). Smaller file size.
    *   **Speed**: Uses "Fast" format (2 bytes per sample). Fast CPU playback (interleaved, no shifting). Larger file size. Best for high sample rates.
*   `--show-cpu-use` (Default: `on`): Visual CPU usage indicator in player.
*   `--no-player`: Generate data only (skip .xex build).
