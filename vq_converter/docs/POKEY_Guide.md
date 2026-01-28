# POKEY Chip Technical Guide: PCM and PDM Audio Playback

## Table of Contents
1. [POKEY Chip Overview](#pokey-chip-overview)
2. [Register Architecture](#register-architecture)
3. [Standard Audio Generation](#standard-audio-generation)
4. [PCM (Pulse Code Modulation)](#pcm-pulse-code-modulation)
5. [PDM (Pulse Density Modulation)](#pdm-pulse-density-modulation)
6. [Implementation Examples](#implementation-examples)
7. [Practical Considerations](#practical-considerations)

---

## POKEY Chip Overview

### What is POKEY?

**POKEY** (POtentiometer and KEYboard Integrated Circuit) is a multi-function LSI chip designed by Doug Neubauer at Atari, Inc. for the Atari 8-bit computer family. First released in 1979 with the Atari 400/800, it handles:

- **Audio synthesis** - 4 independent sound channels
- **Keyboard input** - Key scanning and debouncing
- **Paddle controllers** - Analog-to-digital conversion for potentiometers
- **Serial I/O** - Communication port (SIO bus)
- **Random number generation** - 17-bit polynomial counter
- **Timer interrupts** - Precise timing sources

### Core Audio Architecture

POKEY provides **4 semi-independent audio channels**, each with:
- 8-bit frequency divider (divide-by-N counter)
- 8-bit control register (volume + distortion/noise)
- Pulse generator driven by polynomial counters
- 4-bit volume control (16 discrete levels: 0-15)

**How POKEY Generates Sound:**
Each channel is fundamentally a **pulse generator** that samples from polynomial counters (pseudo-random bit sequences). The frequency divider determines how often the output toggles. Different distortion settings select which polynomial counter(s) to sample from, or bypass them entirely for pure tones.

**Pure square waves** are just one emergent case (distortion modes 5 and 7) where the polynomial counter is not used. Most other modes produce various types of noise or buzzy tones by sampling different polynomial sequences.

**Clock Sources (NTSC):**
- **63.920 kHz** - Default base clock (CPU clock ÷ 28, often rounded to "64 kHz")
- **15.700 kHz** - Alternative base clock (CPU clock ÷ 114, matches scanline timing)
- **1.78977 MHz** - CPU clock for high-precision timing

**Clock Sources (PAL):**
- **63.337 kHz** - Default base clock (CPU clock ÷ 28)
- **15.557 kHz** - Alternative base clock (CPU clock ÷ 114)
- **1.77345 MHz** - CPU clock for high-precision timing

**Note:** Documentation often rounds these to 64 kHz, 15 kHz, and 1.79 MHz for simplicity, but the actual frequencies are slightly different and matter for precise frequency calculations. Use exact values for music playback and emulation.

---

## Register Architecture

### Memory-Mapped Register Addresses

POKEY registers are mapped to memory page **$D200-$D20F** on Atari 8-bit computers (and $D210-$D21F for stereo POKEY systems).

| Address | Write Register | Read Register | Function |
|---------|---------------|---------------|----------|
| $D200 (53760) | AUDF1 | POT0 | Audio Frequency 1 / Paddle 0 |
| $D201 (53761) | AUDC1 | POT1 | Audio Control 1 / Paddle 1 |
| $D202 (53762) | AUDF2 | POT2 | Audio Frequency 2 / Paddle 2 |
| $D203 (53763) | AUDC2 | POT3 | Audio Control 2 / Paddle 3 |
| $D204 (53764) | AUDF3 | POT4 | Audio Frequency 3 / Paddle 4 |
| $D205 (53765) | AUDC3 | POT5 | Audio Control 3 / Paddle 5 |
| $D206 (53766) | AUDF4 | POT6 | Audio Frequency 4 / Paddle 6 |
| $D207 (53767) | AUDC4 | POT7 | Audio Control 4 / Paddle 7 |
| $D208 (53768) | AUDCTL | ALLPOT | Audio Control / All Paddle Status |
| $D209 (53769) | STIMER | KBCODE | Start Timers / Keyboard Code |
| $D20A (53770) | SKREST | RANDOM | Serial/Keyboard Reset / Random Number |
| $D20B (53771) | POTGO | - | Start Paddle Scan |
| $D20D (53773) | SEROUT | SERIN | Serial Output / Serial Input |
| $D20E (53774) | IRQEN | IRQST | IRQ Enable / IRQ Status |
| $D20F (53775) | SKCTL | SKSTAT | Serial/Keyboard Control / Status |

### AUDF1-4: Audio Frequency Registers

**Function:** 8-bit frequency divider value for each channel

The AUDF register contains the "N" value used in a divide-by-N circuit.

**CRITICAL: Timer Period in CPU Cycles (for emulation/precise timing):**

For timers using the **1.79 MHz clock:**
- **Unlinked timer period:** N + 4 cycles
  - +1 cycle because counter must count below $00 (underflow)
  - +3 cycles from internal logic delays (counter stages, underflow detection)
- **Linked 16-bit timer period:** N + 7 cycles
  - +3 additional cycles due to chaining delay (low timer must underflow before high can)

For timers using the **64 KHz or 15 KHz clocks:**
- **Period:** (N + 1) × divisor cycles
  - 64 KHz: (N + 1) × 28 cycles
  - 15 KHz: (N + 1) × 114 cycles
- The +3/+6 cycle delays are absorbed by the clock delay until next pulse

**Audio Frequency Formula (for square waves):**
```
Output Frequency = Clock Frequency / (2 × (AUDF + 1))
```

This simplified formula works for calculating **square wave frequencies** because:
1. In divide-by-2 distortion modes (5, 7, 10, 14), the output toggles on each timer pulse
2. One full cycle requires 2 toggles, so frequency = timer_rate / 2
3. The internal +3/+6 cycle delays effectively cancel out in the divide-by-2 operation

**Important:** 
- For **audio frequency calculations**, use the simplified formula above
- For **emulation, IRQ timing, or serial port**, use the cycle-accurate periods (N+4, N+7)
- POKEY internally increments AUDF by 1, so:
  - AUDF = $00 → divides by 1 (actually 1+1=2)
  - AUDF = $FF → divides by 256

**Frequency Calculation Examples:**

With **63.920 kHz** clock (NTSC):
```
To generate A440 (440 Hz):
63920 / (2 × (AUDF + 1)) = 440
AUDF = (63920 / (2 × 440)) - 1
AUDF = 72.64 - 1 ≈ 72 ($48)

Actual frequency: 63920 / (2 × 73) = 437.81 Hz (2.2 cents flat)
```

With **1.78977 MHz** clock (high precision):
```
AUDF = (1789770 / (2 × 440)) - 1 = 2033.8 - 1 ≈ 2033 ($7F1)
Requires 16-bit mode (channel pairing)

Actual frequency: 1789770 / (2 × 2034) = 440.02 Hz (near-perfect!)
```

**Valid Range:** $00-$FF (0-255)

---

### AUDC1-4: Audio Control Registers

**Function:** Controls volume and waveform distortion for each channel

**Bit Structure:**

| Bit | Function | Values |
|-----|----------|--------|
| 0-3 | **Volume Level** | 0 = silence, 15 = maximum volume |
| 4 | **Volume-Only Mode** | 0 = normal (use frequency), 1 = volume-only (direct output) |
| 5-7 | **Distortion/Noise** | Selects waveform type (see table below) |

#### Volume Bits (0-3): 4-Bit Volume Control

```
Bits 0-3:  0000 = Volume 0  (silent)
           0001 = Volume 1
           0010 = Volume 2
           ...
           1111 = Volume 15 (maximum)
```

**CRITICAL: DAC is NOT Linear!**

The 4-bit DAC has mismatched outputs due to driver ratio differences between the lower 2 bits and upper 2 bits. This causes **wider gaps** between these volume levels:
- **3 → 4** (gap wider than expected)
- **7 → 8** (gap wider than expected)
- **11 → 12** (gap wider than expected)

**Mixing Saturation:**
- **Linear range:** Total volume sum ≤ 15 across all active channels
- **Saturation range:** Volume sum 16-60 shows severe compression
  - Range 16-60 produces only ~2× the amplitude of 15 (not 4×)
  - Two channels at volume 15 = only ~1.5× amplitude of single channel (not 2×)

**Biased Output:**
- Each channel outputs either zero or a **negative voltage** (not positive)
- Changing volume changes DC bias → can cause audible **clicks/pops**
- If channel digital output = 0, no analog output regardless of volume setting

#### Bit 4: Volume-Only Mode (CRITICAL FOR PCM)

**When Bit 4 = 0 (Normal Mode):**
- Channel outputs waveform at frequency set by AUDF
- Distortion bits (5-7) modify the waveform
- Volume bits (0-3) control amplitude

**When Bit 4 = 1 (Volume-Only/Forced Output):**
- **Bypasses frequency divider completely**
- **Ignores other distortion settings (bits 5-7 have no effect)**
- **Output forced to constant '1' producing DC level set by volume bits (0-3)**
- **CRITICAL: Volume-only mode applied AFTER high-pass logic**
  - High-pass flip-flops continue to run (NOT disabled)
  - Volume-only output OVERRIDES high-pass XOR result
  - **Volume-only channels ALWAYS ADD** (no channel inversion applies)
- This is the key to PCM playback!

**Technical Note:** "Volume-only mode" is not a separate hardware mode—it's a specific distortion pattern where the output is forced to a constant level determined by the volume bits. The hardware continuously latches the volume value to the output, bypassing the polynomial counter and frequency divider entirely.

**Example Values:**
```assembly
; Normal mode, pure tone, volume 10
LDA #$A5        ; Binary: 1010 0101
                ; Bits 7-5 = 101 (pure tone)
                ; Bit 4 = 0 (normal mode)
                ; Bits 3-0 = 0101 (volume 5)
STA AUDC1

; Volume-only mode, level 12
LDA #$1C        ; Binary: 0001 1100
                ; Bits 7-5 = 000 (don't matter in forced output)
                ; Bit 4 = 1 (VOLUME-ONLY/FORCED OUTPUT)
                ; Bits 3-0 = 1100 (level 12)
STA AUDC1

; Alternative notation (bits 7-5 ignored anyway)
LDA #$FC        ; Binary: 1111 1100
                ; Also works! Bit 4 = 1, volume = 12
STA AUDC1       ; Behaves identically to $1C
```

#### Distortion Bits (5-7): Waveform Selection

When **Bit 4 = 0** (normal mode), bits 5-7 select the waveform:

**How Distortion Bits Work:**
- **Bit 5:** 0 = sample noise, 1 = square wave
- **Bit 6:** (when bit 5=0) 0 = use 9/17-bit poly, 1 = use 4-bit poly
- **Bit 7:** 0 = 5-bit poly **masks** clock pulses (irregular), 1 = direct clocking (regular)

| Bits 5-7 | Binary | Technical Description | Sound Character | Affected by AUDCTL Bit 7 |
|----------|--------|-----------------------|-----------------|--------------------------|
| 0 | 000 | 5-bit poly clocked 9/17-bit noise | Complex noise | Yes (9/17-bit select) |
| 1 | 001 | 5-bit poly clocked square wave | Buzzy/irregular tone | No |
| 2 | 010 | 5-bit poly clocked 4-bit noise | Medium noise | No |
| 3 | 011 | 5-bit poly clocked square wave | Buzzy/irregular tone | No |
| 4 | 100 | Direct 9/17-bit noise | Clean white noise | Yes (9/17-bit select) |
| 5 | 101 | Direct square wave | **Pure tone** | No |
| 6 | 110 | Direct 4-bit noise | Rough periodic noise | No |
| 7 | 111 | Direct square wave | **Pure tone** | No |

**Key Points:**
- Modes 1 and 3: The 5-bit poly **masks** timer pulses, creating irregular square waves (not noise)
- Modes 5 and 7: No polynomials used, direct square wave generation
- Only modes 0, 2, 4, 8 (using 9/17-bit poly) are affected by AUDCTL bit 7

**Most Common Values:**
- **$A0-$AF** - Pure tone with volume 0-15 (bits 5-7 = 101, bit 4 = 0)
- **$E0-$EF** - Also pure tone (bits 5-7 = 111, bit 4 = 0)
- **$10-$1F** - Volume-only/forced output for PCM (bit 4 = 1, bits 5-7 ignored)

---

### AUDCTL: Audio Control Register ($D208)

**Function:** Global audio configuration affecting all channels

**Bit Mapping:**

| Bit | Hex | Function | Effect When Set (=1) |
|-----|-----|----------|---------------------|
| 0 | $01 | **Clock Base Select** | 15.7 kHz base clock (0 = 63.921 kHz) |
| 1 | $02 | **High-Pass Filter CH2** | Channel 2 filtered by Channel 4 divider |
| 2 | $04 | **High-Pass Filter CH1** | Channel 1 filtered by Channel 3 divider |
| 3 | $08 | **Join Channels 3+4** | 16-bit mode: CH3=LSB, CH4=MSB |
| 4 | $10 | **Join Channels 1+2** | 16-bit mode: CH1=LSB, CH2=MSB |
| 5 | $20 | **1.79 MHz Clock CH3** | Channel 3 uses CPU clock instead of base clock |
| 6 | $40 | **1.79 MHz Clock CH1** | Channel 1 uses CPU clock instead of base clock |
| 7 | $80 | **9-bit Polynomial** | Use 9-bit poly counter for certain distortion modes (0 = 17-bit) |

#### Detailed Bit Functions

**Bit 0: Clock Base Selection**
```
0 = 63.920 kHz base clock (default, NTSC)
    - CPU clock ÷ 28 (often rounded to "64 kHz" in documentation)
    - Good for general music/tones
    - Frequency range: ~125 Hz to 32 kHz
    
1 = 15.700 kHz base clock (NTSC)
    - CPU clock ÷ 114 (matches scanline timing)
    - Lower pitch range
    - Frequency range: ~30 Hz to 7.5 kHz
    - Used for bass/sub-bass effects

Note: PAL machines use 63.337 kHz and 15.557 kHz respectively
```

**Bits 1-2: High-Pass Filters**

POKEY implements crude high-pass filters using D flip-flops and XOR gates:
- Channel 1 can be high-pass filtered using Channel 3's divider as the clock
- Channel 2 can be high-pass filtered using Channel 4's divider as the clock

**How it works:**
1. The channel's output is sampled by a D flip-flop clocked by the "filter" channel
2. The flip-flop's input and output are XOR'd together
3. When input frequency < filter clock rate:
   - Flip-flop output tracks input (both 0 or both 1)
   - XOR sees identical inputs → outputs mostly 0
   - Low frequencies are attenuated (high-pass effect)
4. When input frequency > filter clock rate:
   - Flip-flop can't track rapid changes
   - XOR sees different inputs → passes signal through

**Important:** This is a crude digital filter, not a true analog high-pass. The filter clock rate sets the approximate cutoff frequency.

**Use case:** Creating percussive/metallic effects by filtering noise through a tone generator.

#### ⚠️ CRITICAL: Channel Inversion Behavior

**When high-pass filters are DISABLED (normal operation for most audio):**

POKEY has a hardware quirk that **inverts** the digital output of channels 1 and 2 relative to channels 3 and 4. This occurs because:
1. When high-pass is disabled, the high-pass flip-flop is forced to 1
2. The XOR gate still operates, inverting the channel output
3. This affects channels 1 and 2 only

**Practical Impact on Channel Mixing:**

When playing the **same frequency and phase** on multiple channels:

**These channel combinations ADD (increase amplitude):**
- Channel 1 + Channel 2 (both inverted)
- Channel 3 + Channel 4 (both non-inverted)
- Any volume-only mode channels (always add)

**These channel combinations CANCEL (reduce amplitude or silence):**
- Channel 1 + Channel 3 (one inverted, one not) → **SILENCE**
- Channel 1 + Channel 4 (one inverted, one not) → **SILENCE**
- Channel 2 + Channel 3 (one inverted, one not) → **SILENCE**
- Channel 2 + Channel 4 (one inverted, one not) → **SILENCE**

**Critical for Music Composition:**
- Use CH1+CH2 or CH3+CH4 for unison/doubling effects
- Avoid CH1+CH3, CH1+CH4, CH2+CH3, CH2+CH4 for unison
- Mix inverted/non-inverted channels at different frequencies for interesting timbres

**Exception:** Volume-only mode (bit 4 = 1) is applied AFTER the high-pass XOR, so **volume-only channels always add** regardless of channel number.

**Bits 3-4: 16-Bit Channel Joining**

Joining channels creates a single 16-bit divider from two 8-bit channels:

```
Normal (8-bit):
  Each channel has 256 possible divider values
  Frequency resolution: limited, especially at high pitches

16-bit Mode (Bit 4 = 1, joining CH1+CH2):
  AUDF1 = LSB (Low Byte, fine tuning)
  AUDF2 = MSB (High Byte, coarse tuning)
  Combined divider value = AUDF1 + (AUDF2 × 256)
  65,536 possible values!
  
Example:
  AUDF1 = $F1 (241, LSB)
  AUDF2 = $07 (7, MSB)
  Combined N = 241 + (7 × 256) = 241 + 1792 = 2033
```

**Important:** The first channel in the pair (CH1 or CH3) is always the **low byte**, and the second channel (CH2 or CH4) is the **high byte**. This can be counterintuitive!

**Trade-off:** You lose 2 independent channels but gain precise pitch control.

**Bits 5-6: CPU Clock Mode (1.78977 MHz)**

Switches individual channels to use the fast CPU clock:

```
Bit 5 = 1: Channel 3 runs at 1.78977 MHz (~1.79 MHz)
Bit 6 = 1: Channel 1 runs at 1.78977 MHz (~1.79 MHz)

Why use this?
1. Extremely precise timing for 16-bit mode
2. High-frequency PWM/PDM for pseudo-8-bit audio
3. Ultrasonic carrier frequencies

Frequency range with 1.79 MHz clock:
  ~3.5 kHz to ~895 kHz
```

**Critical Note:** Bits 5 and 6 control **different channels**:
- **Bit 5 ($20)** = Channel **3** at CPU clock
- **Bit 6 ($40)** = Channel **1** at CPU clock

This is a common source of confusion in documentation!

**Bit 7: Polynomial Counter Selection**

```
0 = 17-bit polynomial (default)
    - Longer repeat period (131,071 cycles)
    - More "random" sounding noise
    - Used for white noise, wind, explosions
    
1 = 9-bit polynomial
    - Shorter repeat period (511 cycles)
    - More "metallic" sounding noise
    - Faster cycling, more tonal quality
```

**Important:** This bit only affects distortion modes that use the polynomial counter (modes 0, 2, 4, 6 in AUDC). Pure tone modes (5, 7) ignore this bit entirely. See AUDC distortion table for which modes are affected.

#### Common AUDCTL Configurations

```assembly
; Standard 4-channel audio
LDA #$00
STA AUDCTL      ; All defaults: 63.921 kHz, 8-bit, 17-bit poly

; 16-bit channels 1+2, with 1.79 MHz clock on CH1
LDA #$50        ; Binary: 01010000
STA AUDCTL      ; Bit 6 = 1 (1.79MHz CH1), Bit 4 = 1 (join 1+2)

; 16-bit channels 3+4, with 1.79 MHz clock on CH3
LDA #$28        ; Binary: 00101000
STA AUDCTL      ; Bit 5 = 1 (1.79MHz CH3), Bit 3 = 1 (join 3+4)

; Maximum precision: Both 16-bit pairs
LDA #$78        ; Binary: 01111000
STA AUDCTL      ; Bit 6 = CH1@1.79MHz, Bit 5 = CH3@1.79MHz,
                ; Bit 4 = join 1+2, Bit 3 = join 3+4

; 15 kHz base clock for bass
LDA #$01
STA AUDCTL      ; Bit 0 = 1 (15.7 kHz base)
```

---

### STIMER: Start Timers Register ($D209)

**Function:** Resets all audio divider counters to their AUDF values

**Writing any value** to STIMER:
1. Reloads all timer counters to their AUDF values
2. Sets all output flip-flops to 1
3. **When high-pass filters disabled:** This forces:
   - Channels 1 and 2 → Output OFF (inverted 1 = 0 after XOR)
   - Channels 3 and 4 → Output ON (non-inverted 1 = 1)
4. Synchronizes all channels to start together

**CRITICAL: STIMER does NOT:**
- Fire the timers (no timer underflow occurs)
- Assert IRQs
- Send clock pulses to audio circuits

**Use:** Synchronize multiple channels for chords, phase-locked effects, or precise multi-channel timing.

```assembly
LDA #$00
STA STIMER      ; Reset all audio timers (value doesn't matter)
```

---

### SKCTL: Serial/Keyboard Control ($D20F)

**Function:** Controls serial port, keyboard, and audio initialization

**Audio-Relevant Bits:**

| Bit | Function | Effect |
|-----|----------|--------|
| 0 | Keyboard Debounce | Enable/disable key debouncing |
| 1 | Keyboard Scan | Enable/disable keyboard scanning |
| 2 | Serial Clock | Output clock mode |
| 3 | Serial Mode | Two-tone/normal serial mode |
| 7-6 | Not used | - |

**Audio Initialization:**

POKEY **must** be properly initialized before use. POKEY has no RESET line and powers up in indeterminate state!

**CRITICAL: Initialization Mode (SKCTL bits 0-1 both = 0)**

When both bits 0 and 1 of SKCTL are cleared, POKEY enters initialization mode which:

**Resets/Freezes:**
- 15 KHz clock
- 64 KHz clock  
- 4-bit and 5-bit polynomial noise generators
- 9/17-bit polynomial noise generator (RANDOM)
- Serial port state machines
- Keyboard scan

**Does NOT Reset:**
- IRQEN or IRQST (interrupts may be enabled!)
- KBCODE, SERIN, RANDOM register values
- AUDF1-4, AUDC1-4, AUDCTL registers
- Timer counters
- Audio channel outputs

**Proper Initialization Sequence:**

```assembly
; Step 1: Clear IRQEN FIRST (POKEY may power up with IRQs enabled!)
LDA #$00
STA IRQEN       ; Disable all interrupts

; Step 2: Enter initialization mode
LDA #$00        ; Bits 0-1 = 0 (init mode)
STA SKCTL       ; Resets clocks and polynomial counters

; Step 3: Clear audio registers
STA AUDCTL      ; Reset audio control
STA AUDC1       ; Silence channel 1
STA AUDC2       ; Silence channel 2
STA AUDC3       ; Silence channel 3
STA AUDC4       ; Silence channel 4

; Step 4: Exit initialization mode  
LDA #$03        ; Bits 0-1 = 1 (enable keyboard scan + serial)
STA SKCTL       ; Clocks start running, polynomials begin counting
```

**IMPORTANT:** During initialization mode (SKCTL = $00):
- RANDOM will read $FF (locked)
- All timers using 15/64 KHz clocks will FREEZE (not count)
- Audio using these clocks will be silent until init mode exits

**In BASIC:**
```basic
SOUND 0,0,0,0   ; Null sound statement - initializes POKEY
```

**Why this matters:**
- Serial I/O operations (disk, cassette) modify POKEY registers
- POKEY may have stray IRQs enabled on power-up
- Polynomial counters can lock up if not initialized
- Always reinitialize after serial operations or when starting audio

---

### IRQEN / IRQST: Interrupt Control ($D20E)

**Function:** Enable/check timer and serial interrupts

**IRQEN Bits (Write):**

| Bit | Interrupt Source |
|-----|-----------------|
| 0 | Timer 1 (AUDF1) |
| 1 | Timer 2 (AUDF2) |
| 2 | Timer 4 (AUDF4) |
| 3 | Serial Output Complete |
| 4 | Serial Output Data Needed |
| 5 | Serial Input Data Ready |
| 6 | Other Key (Shift/Ctrl/Break) |
| 7 | Break Key |

**Use for PCM/PDM:**
```assembly
; Enable Timer 1 interrupt for sample playback
LDA #$01        ; Bit 0 = 1
STA IRQEN
```

Timer interrupts fire when the channel divider reaches zero, allowing precise sample timing for PCM/PDM playback.

---

### Polynomial Counters (Noise Generators) - Technical Details

**For Emulation and Advanced Programming**

POKEY contains three polynomial counters (Linear Feedback Shift Registers / LFSRs) that generate pseudo-random noise:

#### 4-bit Polynomial Counter
- **Polynomial:** 1 + x³ + x⁴
- **Period:** 15 bits
- **Pattern:** `000111011001010`
- **Implementation:** XNOR-based maximal-length LFSR
- **Used by:** Distortion modes 2, 6 (when sampling noise)

#### 5-bit Polynomial Counter  
- **Polynomial:** 1 + x³ + x⁵
- **Period:** 31 bits
- **Pattern:** `0000011100100010101111011010011`
- **Implementation:** XNOR-based maximal-length LFSR
- **Used by:** Distortion modes 0, 1, 2, 3 (to mask clock pulses)

#### 9/17-bit Polynomial Counter
- **9-bit mode (AUDCTL bit 7 = 1):**
  - Polynomial: 1 + x⁴ + x⁹
  - Period: 511 bits
- **17-bit mode (AUDCTL bit 7 = 0, default):**
  - Polynomial: 1 + x¹² + x¹⁷  
  - Period: 131,071 bits
- **Implementation:** XNOR-based maximal-length LFSR
- **Used by:** Distortion modes 0, 4, 8 (when sampling noise)
- **Visible to CPU:** 8 bits readable via RANDOM ($D20A)

**Critical Behaviors:**

1. **All run continuously at 1.79 MHz machine clock**
   - Independent of audio channel frequencies
   - Never stop (except in initialization mode)

2. **Noise is sampled, not generated at channel rate**
   - Unlike Atari 2600 TIA (which generates noise at channel rate)
   - Channels sample bits from shared counters running at 1.79 MHz
   - Lower pitch = more bits skipped between samples

3. **Noise delays between channels**
   - Same bit arrives at CH1, then CH2, then CH3, then CH4 (1 cycle apart)
   - Prevents identical noise on all channels

4. **RANDOM register shows inverted bits**
   - Bits read from RANDOM are inverted from internal shift register
   - Bits reaching audio channels are NOT inverted

5. **Aliasing artifacts from sampling**
   - When channel period shares common factors with noise period, artifacts occur
   - **Example:** Period divisible by 15 (4-bit period) = SILENCE
   - **Example:** Period = 511×4 cycles with 9-bit noise = SILENCE
   - Use periods relatively prime to noise periods for best results

6. **Initialization behavior**
   - Init mode forces all counters to known states
   - RANDOM locks at $FF during init mode
   - After exiting init, counters begin immediately from reset state

**Practical Impact:**
- Choose AUDF values carefully to avoid aliasing
- Use 17-bit mode for white noise, 9-bit for more tonal/buzzy noise
- Understand that "noise" is really sampled bits from running counters

---

## Standard Audio Generation

### Basic Sound Synthesis

**Steps to generate a tone:**

1. **Initialize POKEY:**
```assembly
LDA #$00
STA AUDCTL      ; Clear audio control
LDA #$03
STA SKCTL       ; Initialize serial/keyboard
```

2. **Set frequency (AUDF):**
```assembly
LDA #$48        ; Divider value for ~440 Hz at 64kHz clock
STA AUDF1       ; Channel 1 frequency
```

3. **Set volume and waveform (AUDC):**
```assembly
LDA #$A8        ; Binary: 1010 1000
                ; Bits 7-5 = 101 (pure tone)
                ; Bit 4 = 0 (normal mode)
                ; Bits 3-0 = 1000 (volume 8)
STA AUDC1
```

4. **To silence:**
```assembly
LDA #$A0        ; Same waveform, volume 0
STA AUDC1
```

### 16-Bit Mode for Precise Tuning

The 8-bit frequency registers have limited resolution at high frequencies. 16-bit mode solves this:

```assembly
; Play A440 with high precision using channels 1+2 joined

; Initialize
LDA #$00
STA AUDCTL

; Join channels 1+2, use 1.79 MHz for channel 1
LDA #$50        ; Bits: 01010000
STA AUDCTL      ; Bit 6=1 (1.79MHz CH1), Bit 4=1 (join 1+2)

; Calculate: 1789770 / (2 * 440) - 1 = 2033.8 - 1 ≈ 2033 = $07F1
; Remember: CH1 = LSB, CH2 = MSB
LDA #$F1        ; Low byte (LSB)
STA AUDF1       ; Channel 1 gets LSB
LDA #$07        ; High byte (MSB)
STA AUDF2       ; Channel 2 gets MSB

; Combined value: $F1 + ($07 × 256) = 241 + 1792 = 2033

; Set volume/waveform
LDA #$A8        ; Pure tone, volume 8
STA AUDC1       ; Only channel 1 produces audible output
                ; (Channel 2 is used as part of the 16-bit divider)
```

**Critical:** When channels are joined, only the first channel (CH1 in this case) produces audio output. The second channel (CH2) contributes its AUDF value as the high byte but does not output sound independently.

### Distortion/Noise Examples

```assembly
; White noise (explosion effect)
LDA #$FF
STA AUDF1       ; Low frequency
LDA #$88        ; Distortion 4 (17-bit poly), volume 8
STA AUDC1

; Buzzy bass
LDA #$20
STA AUDF1       ; Medium frequency
LDA #$2C        ; Distortion 1 (5-bit poly), volume 12
STA AUDC1

; Pure tone (melody)
LDA #$48
STA AUDF1
LDA #$AF        ; Distortion 5 (pure), volume 15
STA AUDC1
```

---

## PCM (Pulse Code Modulation)

### Concept

PCM on POKEY works by **bypassing the internal oscillators** and directly controlling the speaker output voltage through the volume bits. By updating the volume thousands of times per second, you reconstruct a digitized waveform.

### How It Works

**Normal Operation:**
```
AUDF → Divider → Square Wave → Volume Control → Speaker
```

**Volume-Only Mode (PCM):**
```
AUDC (bits 0-3) → Output Latch → Speaker
                ↑
        CPU writes sample values
```

The speaker cone position becomes proportional to the value written to bits 0-3 of AUDC.

**Technical Detail:** The output is not true DC voltage—it's a **latched digital value** that holds constant until the next write. POKEY internally maintains an output latch that continuously drives the audio output at the specified volume level. The latch is clocked by POKEY's internal timing, so rapid updates can cause brief glitches if not synchronized properly.

**Electrical Behavior:**
- Each write to AUDC updates the output latch
- The latch holds the value until the next write
- The analog output voltage is determined by a resistor ladder DAC
- Writes are synchronized to POKEY's clock domain (can cause zipper noise if updates occur at irregular intervals)

### Technical Specifications

**Resolution:** 4-bit (16 discrete levels)
- Sample values: 0 to 15
- Dynamic range: ~24 dB (6 dB per bit × 4 bits)
- Quantization step: 1/16 of full scale

**Sample Rate:** Limited by CPU speed
- Practical range: 3-15 kHz
- Quality sweet spot: 4-8 kHz
- Higher rates require disabling interrupts/DMA

**Audio Quality:**
- Low fidelity by modern standards
- Noticeable quantization noise ("hiss" or "graininess")
- Good enough for speech and simple sound effects
- Characteristic "crunchy" or "lo-fi" sound

**CPU Usage:** Very high
- CPU must update AUDC 4,000-15,000 times per second
- Little processing time available for game logic
- Often used for title screens or cutscenes

### Register Configuration for PCM

**Step 1: Initialize POKEY**
```assembly
LDA #$00
STA AUDCTL      ; Clear audio control (optional)
LDA #$03
STA SKCTL       ; Initialize POKEY
```

**Step 2: Select Channel and Enable Volume-Only Mode**
```assembly
; For Channel 1:
LDA #$10        ; Binary: 00010000
                ; Bit 4 = 1 (VOLUME-ONLY MODE)
                ; Bits 0-3 = 0 (initial volume level)
STA AUDC1
```

**Important:** The AUDF1 register is now **ignored**. You don't need to set it for PCM.

**Step 3: Stream Sample Data**

The core PCM loop writes 4-bit sample values with bit 4 set:

```assembly
PCM_LOOP:
    LDX sample_index
    LDA sample_buffer,X     ; Load 4-bit sample (0-15)
    ORA #$10                ; Set bit 4 (volume-only mode)
    STA AUDC1               ; Output to speaker
    
    ; Timing delay to achieve desired sample rate
    ; (see timing methods below)
    
    INX
    CPX sample_length
    BNE PCM_LOOP
```

### PCM Timing Methods

**Method 1: Vertical Blank Interrupt (Simple but Low Quality)**

Use the 50/60 Hz VBI for low sample rate playback:

```assembly
VBI_HANDLER:
    ; Called 60 times per second (NTSC)
    LDA next_sample
    ORA #$10
    STA AUDC1
    RTS

; Sample rate = 60 Hz (terrible quality, but simple)
```

**Method 2: Tight Loop with Cycle Counting**

Count CPU cycles for precise timing:

```assembly
PCM_LOOP:
    LDA sample_buffer,X     ; 4+ cycles
    ORA #$10                ; 2 cycles
    STA AUDC1               ; 4 cycles
    INX                     ; 2 cycles
    NOP                     ; 2 cycles (timing adjustment)
    NOP                     ; 2 cycles
    CPX #END                ; 2 cycles
    BNE PCM_LOOP            ; 3 cycles (when taken)
    
; Total: ~21 cycles per sample
; At 1.79 MHz: 1,790,000 / 21 ≈ 85 kHz sample rate
; (Too fast! Need more delay cycles)
```

**Method 3: Timer Interrupt (Best Quality)**

Use POKEY timer for precise sample rate:

```assembly
; Setup: Use Channel 4 as a timer
SETUP_TIMER:
    LDA #$4F        ; Value for ~8 kHz sample rate
    STA AUDF4       ; Set timer divider
    
    LDA #$01        ; Enable Timer 1 interrupt
    STA IRQEN
    
    ; Set interrupt vector to point to sample handler
    RTS

TIMER_IRQ_HANDLER:
    LDA next_sample
    ORA #$10
    STA AUDC1       ; Channel 1 plays PCM
    ; Update sample pointer
    RTS
```

**Method 4: Display List Interrupt (DLI)**

Use DLI for sample updates synchronized with screen refresh:

```assembly
DLI_HANDLER:
    ; Called once per scanline (262 times per frame NTSC)
    ; Sample rate ≈ 262 × 60 = 15.7 kHz
    LDA next_sample
    ORA #$10
    STA AUDC1
    RTI
```

### Sample Rate Calculations

To achieve a specific sample rate:

```
Desired Rate (Hz) = Clock Frequency / Divider

For 8 kHz sample rate using timer interrupt:
  64000 / 8000 = 8
  AUDF4 = 8 - 1 = 7
```

**Common Sample Rates:**

| Target Rate | Clock | AUDF Value | Quality |
|-------------|-------|------------|---------|
| 3.9 kHz | 64 kHz | $0F (15) | Low, speech barely intelligible |
| 7.8 kHz | 64 kHz | $07 (7) | Medium, recognizable speech |
| 15.6 kHz | 64 kHz | $03 (3) | Good, clear speech |

### PCM Sample Format

**4-Bit Unsigned:**
```
0x0 = Minimum (speaker fully in)
0x7 = Middle position
0xF = Maximum (speaker fully out)
```

**Conversion from 8-bit:**
```c
// Right-shift to convert 8-bit to 4-bit
uint8_t sample_8bit = input[i];     // 0-255
uint8_t sample_4bit = sample_8bit >> 4;  // 0-15

// Write to POKEY
AUDC1 = 0x10 | sample_4bit;
```

**Pre-Processing Tips:**
1. **Normalize:** Scale input to use full 0-15 range
2. **DC Offset:** Center around 7-8 to prevent clicking
3. **Dithering:** Add random noise before quantization to reduce "banding"

### PCM Code Example (Complete)

```assembly
;============================================
; Simple PCM Player for POKEY
; Plays 4-bit samples at ~8 kHz
;============================================

AUDF4   = $D206
AUDC1   = $D201
AUDC4   = $D207
AUDCTL  = $D208
SKCTL   = $D20F
IRQEN   = $D20E

sample_ptr  = $80   ; Zero-page pointer
sample_len  = $82   ; Sample length

;--------------------------------------------
; Initialize PCM Playback
;--------------------------------------------
init_pcm:
    ; Initialize POKEY
    LDA #$00
    STA AUDCTL
    LDA #$03
    STA SKCTL
    
    ; Set up Channel 1 for volume-only
    LDA #$10        ; Volume-only mode, initial level 0
    STA AUDC1
    
    ; Set up Channel 4 as sample rate timer
    LDA #$07        ; ~8 kHz sample rate
    STA AUDF4
    LDA #$A0        ; Pure tone (will be inaudible)
    STA AUDC4
    
    ; Enable timer interrupt
    LDA #$04        ; Timer 4 interrupt
    STA IRQEN
    
    ; Set up interrupt vector
    ; (System-dependent, see OS documentation)
    
    RTS

;--------------------------------------------
; Timer Interrupt Handler
;--------------------------------------------
pcm_irq:
    ; Save registers
    PHA
    TXA
    PHA
    
    ; Get next sample
    LDY #$00
    LDA (sample_ptr),Y
    
    ; Output to Channel 1
    ORA #$10        ; Set volume-only bit
    STA AUDC1
    
    ; Increment pointer
    INC sample_ptr
    BNE skip_hi
    INC sample_ptr+1
    
skip_hi:
    ; Decrement length counter
    LDA sample_len
    BNE dec_lo
    DEC sample_len+1
dec_lo:
    DEC sample_len
    
    ; Check if done
    LDA sample_len
    ORA sample_len+1
    BNE continue
    
    ; Playback complete - disable interrupt
    LDA #$00
    STA IRQEN
    
continue:
    ; Restore registers
    PLA
    TAX
    PLA
    RTI

;--------------------------------------------
; Sample Data
;--------------------------------------------
sample_data:
    .byte $0, $2, $5, $8, $B, $E, $F, $E  ; Sine-like wave
    .byte $B, $8, $5, $2, $0, $1, $3, $1
    ; ... more sample data
```

### PCM Use Cases

**Ideal for:**
- Speech samples ("Ghostbusters!", "Elf needs food badly!")
- Short sound effects (impacts, explosions)
- Title screen music (when nothing else is running)
- Voice announcements

**Not suitable for:**
- Background music during gameplay (too much CPU)
- High-fidelity recording playback
- Multiple simultaneous samples (unless very low rate)

### PCM Audio Quality Examples

**Historical Examples on Atari 8-bit:**
- **Ghostbusters** (1984) - "Ghostbusters!" speech sample
- **Gauntlet** (arcade/7800 with POKEY) - "Elf needs food badly"
- **Ballblazer** - Sampled crowd cheering
- **APE Sampler** - Various speech demos

---

## PDM (Pulse Density Modulation)

### Concept

PDM overcomes the 4-bit limitation by using **temporal dithering** - switching between volume levels so rapidly that the speaker membrane (and human ear) perceive an *average* value between the discrete steps.

**Key Insight:**
```
Cannot write: 7.5 to AUDC (not possible)
But can write: 7, 8, 7, 8, 7, 8... at 100 kHz
Speaker hears: Effectively 7.5 (averaged)
```

This allows **simulated 8-bit or higher resolution** from 4-bit hardware.

### Physical Principles

**Speaker Inertia:**
- Speaker cones have mass and cannot respond instantly
- High-frequency switching (>20 kHz) gets physically averaged
- Low-pass filtering effect of speaker itself

**Human Hearing:**
- Cannot perceive individual pulses above ~20 kHz
- Hears only the averaged amplitude
- "Ultrasonic PWM" becomes audible amplitude

### PDM vs PCM Comparison

| Feature | PCM (Standard) | PDM (Advanced) |
|---------|----------------|----------------|
| **Bit Depth** | 4-bit (hardware) | 8-bit effective (simulated) |
| **Levels** | 16 | 256 |
| **Quality** | Lo-fi, noisy | Hi-fi, clean |
| **CPU Usage** | High (4-15 kHz updates) | Extreme (100-200 kHz updates) |
| **Complexity** | Simple | Very complex |
| **Timing** | Forgiving | Cycle-perfect required |
| **Use Cases** | In-game speech | Demos, title screens |

### PDM Implementation Approaches

There are **two main PDM techniques** used on POKEY:

#### Method 1: Single-Channel High-Frequency PWM

**Principle:** Toggle between adjacent volume levels at ultrasonic rates

**Example - Creating level 7.5:**
```
Time:     0μs   10μs  20μs  30μs  40μs  50μs
Value:     7     8     7     8     7     8
Average:        7.5   7.5   7.5   7.5   7.5
```

**Requirements:**
- Toggle rate: 50-200 kHz (ultrasonic)
- Uses POKEY 1.79 MHz clock + timer interrupts
- Requires cycle-perfect timing

**Register Configuration:**
```assembly
; Use 1.79 MHz clock for channel 1
LDA #$60        ; Bit 6 = 1 (1.79MHz CH1), Bit 5 = 1 (1.79MHz CH3)
STA AUDCTL

; Set very short timer period
LDA #$01        ; Divide by 2 = ~895 kHz toggle rate
STA AUDF1

; Enable volume-only mode
LDA #$10
STA AUDC1
```

**PWM Algorithm (Error Accumulator):**
```c
int16_t error_accumulator = 0;
uint8_t current_level;

for each sample period {
    error_accumulator += sample_value;  // 0-255
    
    if (error_accumulator >= 128) {
        current_level = (sample_value >> 4) + 1;  // Upper level
        error_accumulator -= 128;
    } else {
        current_level = (sample_value >> 4);      // Lower level
    }
    
    AUDC1 = 0x10 | current_level;
    
    // Repeat at ultrasonic rate (e.g., 100 kHz)
}
```

#### Method 2: Dual-Channel Weighted Mixing (Most Common)

**Principle:** Use two channels to represent MSB and LSB nibbles separately

**Architecture:**
```
Channel A (AUDC1): Plays MSB nibble (upper 4 bits) at full duty cycle
Channel B (AUDC2): Plays LSB nibble (lower 4 bits) at 1/16 duty cycle

Speaker receives analog sum ≈ (MSB × 16) + LSB
```

**Theory:** An 8-bit sample value can be decomposed:
```
8-bit sample = 0xAB (171 decimal)
- MSB nibble = 0xA (10)  → contributes 10 × 16 = 160
- LSB nibble = 0xB (11)  → contributes 11 × 1 = 11
- Total ≈ 160 + 11 = 171
```

**Implementation:**
```
Channel A outputs: Level 10 continuously
Channel B outputs: Level 11 for 1/16 of sample period, 0 otherwise

Time-averaged at speaker:
  Channel A contributes: 10 × 1.0 = 10.0
  Channel B contributes: 11 × 0.0625 = 0.6875
  Total effective level: 10.6875
  
Scaled to 8-bit: 10.6875 × 16 ≈ 171 ✓
```

**Important Caveats:**

1. **Analog Mixing:** The channels are mixed in the analog domain through POKEY's output resistor network. This is **not perfect digital addition**—component tolerances and nonlinearities affect the result.

2. **Effective Resolution:** Due to DAC nonlinearity and imperfect mixing, you get approximately **6-7 effective bits** rather than a perfect 8 bits.

3. **Phase Alignment:** Both channels must be perfectly synchronized. Even small timing errors produce audible distortion.

4. **DC Offset:** POKEY outputs are not symmetric around zero. The LSB channel must be carefully calibrated to avoid DC bias that could damage speakers or cause clicking.

**Timing Diagram:**
```
Sample Period (8 μs at 125 kHz):

Channel A: |██████████████| Level 10 entire period
Channel B: |█|             | Level 11 for 0.5 μs, then 0
           
Speaker:   |██████████████| Effective level ≈ 10.6875
```

### Dual-Channel PDM Register Configuration

**AUDCTL Setup:**
```assembly
; Use 1.79 MHz clock for channel 1 (main signal)
; Use channel 3 as timer for channel 2 (pulse width)
LDA #$68        ; Binary: 01101000
                ; Bit 6 = 1 (1.79MHz CH1)
                ; Bit 5 = 1 (1.79MHz CH3) 
                ; Bit 3 = 1 (join CH3+4 for precise timing)
STA AUDCTL
```

**Channel Configuration:**
```assembly
; Channel 1: MSB nibble (continuous)
LDA #$10        ; Volume-only mode
STA AUDC1

; Channel 2: LSB nibble (pulsed)
LDA #$10        ; Volume-only mode
STA AUDC2

; Channel 3/4: Timer for LSB pulse width (1/16 duty)
LDA #$0F        ; Adjust for 1/16 duty cycle
STA AUDF3
```

### Dual-Channel PDM Algorithm

**High-Level Logic:**
```assembly
PDM_SAMPLE_LOOP:
    ; Get 8-bit sample (0-255)
    LDA sample_8bit
    
    ; Extract MSB nibble (upper 4 bits)
    LSR A
    LSR A
    LSR A
    LSR A
    ORA #$10
    STA AUDC1       ; Channel 1 = MSB continuously
    
    ; Extract LSB nibble (lower 4 bits)
    LDA sample_8bit
    AND #$0F
    STA lsb_temp
    
    ; Pulse LSB channel for 1/16 of sample period
    LDA lsb_temp
    ORA #$10
    STA AUDC2       ; Turn on LSB channel
    
    ; Wait 1/16 sample period (very short)
    ; (Use timer interrupt or cycle counting)
    
    LDA #$10        ; Turn off LSB channel (volume 0)
    STA AUDC2
    
    ; Wait 15/16 sample period
    ; (Timer interrupt for precise timing)
    
    JMP PDM_SAMPLE_LOOP
```

**Timing is Critical:**

For 8 kHz sample rate (125 μs per sample):
- LSB pulse duration: 125 μs / 16 ≈ 7.8 μs
- MSB hold: Full 125 μs

```assembly
; Use timer interrupts for precise pulse timing
TIMER_SETUP:
    ; Main sample rate timer (8 kHz = 125 μs period)
    LDA #$DE        ; 64kHz / 223 ≈ 287 Hz × 2 = ...
                    ; (Calculate based on desired rate)
    STA AUDF4
    
    ; LSB pulse timer (1/16 of sample period)
    LDA #$0D        ; Very short pulse
    STA AUDF3
```

### Complete PDM Implementation (Dual-Channel)

```assembly
;============================================
; Advanced PDM Player (Dual-Channel 8-bit)
; Channels 1+2 for audio
; Channels 3+4 as timers
;============================================

AUDF1   = $D200
AUDC1   = $D201
AUDF2   = $D202
AUDC2   = $D203
AUDF3   = $D204
AUDC3   = $D205
AUDF4   = $D206
AUDC4   = $D207
AUDCTL  = $D208
SKCTL   = $D20F
IRQEN   = $D20E

sample_8bit = $80   ; Current 8-bit sample
lsb_nibble  = $81   ; LSB temporary storage

;--------------------------------------------
; Initialize PDM System
;--------------------------------------------
init_pdm:
    ; Initialize POKEY
    LDA #$00
    STA AUDCTL
    LDA #$03
    STA SKCTL
    
    ; Set up audio control
    ; Bit 6 = 1.79MHz CH1, Bit 5 = 1.79MHz CH3
    LDA #$60
    STA AUDCTL
    
    ; Enable volume-only mode on channels 1 and 2
    LDA #$10
    STA AUDC1       ; MSB channel
    STA AUDC2       ; LSB channel (initially off)
    
    ; Set up timers
    ; (Values depend on desired sample rate)
    LDA #$80        ; Main sample rate
    STA AUDF4
    
    LDA #$08        ; LSB pulse width (1/16 of sample)
    STA AUDF3
    
    ; Enable timer interrupts
    LDA #$06        ; Timers 3 and 4
    STA IRQEN
    
    RTS

;--------------------------------------------
; Main Sample Interrupt (Timer 4)
; Called at sample rate (e.g., 8 kHz)
;--------------------------------------------
sample_irq:
    ; Load next 8-bit sample
    LDA next_sample     ; 0-255
    STA sample_8bit
    
    ; Extract MSB (upper 4 bits)
    LSR A
    LSR A
    LSR A
    LSR A
    ORA #$10
    STA AUDC1           ; Output MSB to channel 1
    
    ; Extract LSB (lower 4 bits)
    LDA sample_8bit
    AND #$0F
    STA lsb_nibble
    
    ; Turn ON LSB channel (timer 3 will turn it off)
    ORA #$10
    STA AUDC2
    
    ; Advance sample pointer
    ; ...
    
    RTI

;--------------------------------------------
; LSB Pulse Interrupt (Timer 3)
; Called after 1/16 of sample period
;--------------------------------------------
lsb_pulse_irq:
    ; Turn OFF LSB channel (back to volume 0)
    LDA #$10
    STA AUDC2
    
    RTI
```

### PDM Quality vs CPU Trade-off

**Achievable Quality Levels:**

| Implementation | Effective Bits | Sample Rate | CPU Usage | Use Case |
|----------------|----------------|-------------|-----------|----------|
| 4-bit PCM | 4-bit | 4-8 kHz | 40-80% | In-game speech |
| Single PWM | 5-6 bit | 8-10 kHz | 95% | Enhanced samples |
| Dual-channel | 6-7 bit | 8-15 kHz | 99% | Demo music |
| Triple-channel | 7-8 bit | 10-20 kHz | 100% | Title screens only |

**Important: Effective Bit Depth Limitation**

While dual-channel PDM theoretically provides 8-bit resolution (256 levels), the POKEY hardware does **not achieve true 8-bit quality** in practice:

1. **DAC Nonlinearity:** The 4-bit volume DAC uses a resistor ladder that is not perfectly linear. Volume steps are not exactly equal in voltage.

2. **Channel Mixing:** When two channels are mixed, the combination is done in the analog domain through the audio mixing circuit. This mixing is **not perfectly additive** due to component tolerances and impedance effects.

3. **Chip Variations:** Different POKEY chip revisions (C012294, quad POKEYs, etc.) have slightly different analog characteristics.

**Practical Result:** Dual-channel PDM typically achieves **6-7 bits of effective resolution** (ENOB - Effective Number of Bits) rather than a perfect 8 bits. This is still vastly superior to 4-bit PCM and produces high-quality audio comparable to early samplers.

**Testing Recommendation:** Always test PDM implementations on real hardware. Emulators often assume perfect linearity and may sound better than actual hardware, leading to disappointment when running on a real Atari.

### PDM Practical Considerations

**CPU Requirements:**
- **100% CPU dedication** for dual-channel 8-bit
- Must disable screen DMA (ANTIC off) for consistent timing
- OS interrupts must be disabled or handled perfectly
- No game logic can run simultaneously

**AUDCTL Configuration:**
```assembly
; Maximum quality configuration
LDA #$60        ; 1.79MHz on channels 1 and 3
STA AUDCTL

; Disable ANTIC to prevent DMA steal cycles
LDA #$00
STA DMACTL      ; Turn off display DMA
```

**Synchronization Critical:**
```
If ONE write to AUDC1/AUDC2 is delayed by even a few cycles:
→ Audible "click" or distortion
→ Waveform phase error
→ Cumulative timing drift

Solution: Disable ALL interrupts during playback
```

**Cycle-Perfect Code:**
```assembly
; Each instruction must execute in exact cycles
PDM_LOOP:
    LDA sample,X    ; 4 cycles
    LSR A           ; 2 cycles
    LSR A           ; 2 cycles
    LSR A           ; 2 cycles
    LSR A           ; 2 cycles
    ORA #$10        ; 2 cycles
    STA AUDC1       ; 4 cycles
    ; Total: 18 cycles (exactly!)
```

### Historical PDM Demos

**Famous Atari 8-bit PDM Examples:**
- **Numen Demo** (2001) - 8-bit quality music
- **Yoomp!** Title Screen - High-quality intro music
- Various "Atari SAP Music Player" high-quality conversions
- Modern homebrew demos showcasing PDM

**Quality Comparison:**
- Standard PCM: Sounds like telephone quality
- Dual-channel PDM: Sounds like Amiga/SNES quality
- Modern PDM: Approaches CD quality (with careful coding)

---

## Implementation Examples

### Example 1: Simple 4-bit PCM Player

```assembly
;============================================
; Minimal PCM Player
; Uses VBI for ~60 Hz updates (very low quality demo)
;============================================

        .include "atari.inc"

sample_ptr = $80
sample_idx = $82

        org $2000

start:
        ; Disable interrupts
        SEI
        
        ; Initialize POKEY
        LDA #$00
        STA AUDCTL
        LDA #$03
        STA SKCTL
        
        ; Set channel 1 to volume-only mode
        LDA #$10
        STA AUDC1
        
        ; Set up VBI vector
        LDA #<vbi_handler
        STA $0222       ; VVBLKD
        LDA #>vbi_handler
        STA $0223
        
        ; Enable interrupts
        CLI
        
loop:
        JMP loop

;--------------------------------------------
; VBI Handler - plays next sample
;--------------------------------------------
vbi_handler:
        LDX sample_idx
        
        ; Get sample
        LDA sample_data,X
        
        ; Output to POKEY
        ORA #$10        ; Set volume-only bit
        STA AUDC1
        
        ; Advance
        INX
        CPX #sample_end-sample_data
        BNE no_wrap
        LDX #$00
no_wrap:
        STX sample_idx
        
        JMP $E462       ; Return through OS

;--------------------------------------------
; Sample Data (4-bit sine wave)
;--------------------------------------------
sample_data:
        .byte $8,$A,$C,$E,$F,$E,$C,$A
        .byte $8,$6,$4,$2,$0,$2,$4,$6
sample_end:

        run start
```

### Example 2: Timer-Based PCM (Better Quality)

```assembly
;============================================
; Timer-Based PCM Player (~8 kHz)
;============================================

        .include "atari.inc"

AUDF1   = $D200
AUDC1   = $D201
AUDF4   = $D206
AUDCTL  = $D208
IRQEN   = $D20E
SKCTL   = $D20F

sample_ptr  = $80
sample_len  = $82

        org $2000

start:
        ; Initialize
        JSR init_pcm
        
        ; Set sample parameters
        LDA #<sample_data
        STA sample_ptr
        LDA #>sample_data
        STA sample_ptr+1
        
        LDA #<(sample_end-sample_data)
        STA sample_len
        LDA #>(sample_end-sample_data)
        STA sample_len+1
        
        ; Start playback
        JSR start_pcm
        
wait:
        LDA sample_len      ; Wait until done
        ORA sample_len+1
        BNE wait
        
        RTS

;--------------------------------------------
init_pcm:
        ; Initialize POKEY
        LDA #$00
        STA AUDCTL
        LDA #$03
        STA SKCTL
        
        ; Channel 1: volume-only mode
        LDA #$10
        STA AUDC1
        
        ; Channel 4: timer for ~8 kHz
        ; 64kHz / 8kHz = 8, so AUDF4 = 7
        LDA #$07
        STA AUDF4
        
        RTS

;--------------------------------------------
start_pcm:
        ; Enable timer 4 interrupt
        LDA #$04
        STA IRQEN
        
        ; Set IRQ vector
        SEI
        LDA #<timer_irq
        STA $0216       ; VIMIRQ
        LDA #>timer_irq
        STA $0217
        CLI
        
        RTS

;--------------------------------------------
timer_irq:
        ; Save registers
        PHA
        
        ; Check if samples remain
        LDA sample_len
        ORA sample_len+1
        BEQ irq_done
        
        ; Get next sample
        LDY #$00
        LDA (sample_ptr),Y
        ORA #$10
        STA AUDC1
        
        ; Increment pointer
        INC sample_ptr
        BNE no_carry
        INC sample_ptr+1
no_carry:
        
        ; Decrement length
        LDA sample_len
        BNE dec_lo
        DEC sample_len+1
dec_lo:
        DEC sample_len
        
        JMP irq_exit

irq_done:
        ; Disable interrupt
        LDA #$00
        STA IRQEN
        
irq_exit:
        PLA
        RTI

;--------------------------------------------
sample_data:
        .byte $8,$9,$A,$B,$C,$D,$E,$F
        .byte $E,$D,$C,$B,$A,$9,$8,$7
        .byte $6,$5,$4,$3,$2,$1,$0,$1
        .byte $2,$3,$4,$5,$6,$7,$8,$8
        ; ... more samples
sample_end:

        run start
```

---

## Practical Considerations

### PCM Best Practices

**1. Sample Preparation:**
```
Original: 16-bit 44.1 kHz stereo WAV
    ↓ Downmix to mono
    ↓ Resample to 8 kHz
    ↓ Quantize to 4-bit
    ↓ Add dithering
Result: Atari-ready 4-bit PCM
```

**2. Optimization Tips:**
- Use zero-page addressing for sample pointers (faster)
- Unroll loops for time-critical sections
- Pre-calculate OR #$10 into sample data
- Use self-modifying code for pointer updates

**3. Mixing PCM with Other Sounds:**
```assembly
; Use channel 1 for PCM, channels 2-4 for music
LDA pcm_sample
ORA #$10
STA AUDC1       ; PCM on channel 1

LDA #$28
STA AUDF2       ; Music on channel 2
LDA #$A8
STA AUDC2
```

### PDM Best Practices

**1. Disable Everything:**
```assembly
; Turn off display DMA
LDA #$00
STA DMACTL

; Disable OS interrupts
SEI

; Disable NMI (display list interrupts)
LDA #$00
STA NMIEN
```

**2. Cycle-Perfect Timing:**
```assembly
; Every code path must be EXACT same cycles
PDM_LOOP:
    LDA sample,X    ; 4+ cycles
    LSR A           ; 2
    LSR A           ; 2
    LSR A           ; 2
    LSR A           ; 2
    ORA #$10        ; 2
    STA AUDC1       ; 4
    NOP             ; 2 (timing adjustment)
    INX             ; 2
    CPX #END        ; 2
    BCC PDM_LOOP    ; 3 (when taken)
; Total: 25 cycles per iteration
```

**3. Testing on Real Hardware:**
- Emulators may not accurately simulate timing
- Test on multiple POKEY revisions (some have bugs)
- Use oscilloscope to verify waveforms
- Listen on real TV speaker (filtering differs)

### Common Problems and Solutions

**Problem: Clicking/Popping Noises**
```
Cause: Abrupt volume changes, DC offset
Solution: Fade in/out, center samples around DC midpoint
```

**Problem: Hissing Background Noise**
```
Cause: 4-bit quantization noise
Solution: Add dithering during conversion, use PDM
```

**Problem: Timing Drift**
```
Cause: Missed interrupts, DMA cycles
Solution: Disable ANTIC, use cycle-perfect code
```

**Problem: Volume Too Low**
```
Cause: Poor mixing, RF modulator attenuation
Solution: Normalize samples to full 0-15 range
```

**Problem: Sound Suddenly Changes or Resets**
```
Cause: OS shadow registers being written during VBLANK
Solution: See detailed explanation below
```

### OS Shadow Register Management

The Atari OS maintains **shadow registers** for POKEY audio that are automatically copied to the hardware during the Vertical Blank interrupt (60 times per second on NTSC).

**Shadow Registers:**
```
Hardware          Shadow RAM
--------          ----------
AUDF1 ($D200) ←→  $D200 (no shadow in OS)
AUDC1 ($D201) ←→  $D201 (no shadow in OS)
AUDF2 ($D202) ←→  $D202 (no shadow in OS)
AUDC2 ($D203) ←→  $D203 (no shadow in OS)
AUDF3 ($D204) ←→  $D204 (no shadow in OS)
AUDC3 ($D205) ←→  $D205 (no shadow in OS)
AUDF4 ($D206) ←→  $D206 (no shadow in OS)
AUDC4 ($D207) ←→  $D207 (no shadow in OS)
AUDCTL ($D208) ←→  $D208 (no shadow in OS)

Note: Basic SOUND statement uses shadow locations
      that get copied during VBI
```

**When Problems Occur:**

1. **Using BASIC SOUND command:** The SOUND statement updates both hardware and OS shadow locations. During VBI, shadows are copied back to hardware.

2. **Direct hardware writes:** If you write directly to $D201-$D208 while BASIC or OS is running, the VBI will overwrite your values 60 times per second.

**Solutions:**

```assembly
; Method 1: Disable VBI during critical audio
SEI             ; Disable interrupts
; ... your PCM/PDM code ...
CLI             ; Re-enable interrupts

; Method 2: Update shadow registers too
LDA sample
ORA #$10
STA $D201       ; Hardware
STA $0201       ; Shadow (if OS uses it)

; Method 3: Use deferred VBI
; Set immediate VBI vector to bypass OS shadowing
```

**BASIC Users:**
```basic
REM Initialize POKEY and clear shadows
SOUND 0,0,0,0

REM For critical timing, use machine language
REM that disables VBI
```

### Performance Metrics

**CPU Cycles Available (NTSC):**
```
Frame time: 1/60 second = 16,667 μs
CPU cycles per frame: 1,790,000 / 60 ≈ 29,833 cycles

With screen DMA active: ~60% available = ~18,000 cycles
Without screen DMA: ~95% available = ~28,000 cycles
```

**Sample Rate vs CPU Usage (4-bit PCM):**
```
4 kHz:  ~30 cycles/sample = 120,000 cycles/sec = 6.7% CPU
8 kHz:  ~30 cycles/sample = 240,000 cycles/sec = 13.4% CPU
15 kHz: ~30 cycles/sample = 450,000 cycles/sec = 25.1% CPU
```

**Sample Rate vs CPU Usage (8-bit PDM):**
```
8 kHz with dual-channel: ~200 cycles/sample = 1,600,000 cycles/sec = 89% CPU
(Requires disabling display for consistent timing)
```

---

## Conclusion

### Summary Table

| Technique | Resolution | Quality | CPU | Complexity | Use Case |
|-----------|-----------|---------|-----|------------|----------|
| **Standard Audio** | N/A | Synth | Low | Simple | Game music/SFX |
| **4-bit PCM** | 4-bit | Low | High | Medium | Speech samples |
| **Single PWM PDM** | 5-6 bit | Medium | Very High | High | Enhanced audio |
| **Dual-Channel PDM** | 6-7 bit effective | High | Extreme | Very High | Demo music |

**Note:** "Effective" resolution accounts for DAC nonlinearity and analog mixing imperfections.

### Key Takeaways

**POKEY Audio Registers:**
- **AUDF1-4** ($D200, $D202, $D204, $D206): Frequency dividers
- **AUDC1-4** ($D201, $D203, $D205, $D207): Volume + distortion
  - Bits 0-3: Volume (0-15)
  - Bit 4: **Volume-only/forced output** (critical for PCM/PDM)
  - Bits 5-7: Distortion/noise selection (ignored when bit 4 = 1)
- **AUDCTL** ($D208): Global control
  - Bit 0: Clock base (63.921 kHz / 15.7 kHz)
  - Bit 3: Join channels 3+4 (CH3=LSB, CH4=MSB)
  - Bit 4: Join channels 1+2 (CH1=LSB, CH2=MSB)
  - Bit 5: 1.79 MHz clock for Channel **3**
  - Bit 6: 1.79 MHz clock for Channel **1**
  - Bit 7: Polynomial length (only affects noise modes)

**Important Clarifications:**
- Bits 5 and 6 control **different channels** (often confused in documentation)
- In 16-bit mode, the **first** channel (1 or 3) is LSB, **second** (2 or 4) is MSB
- Clock frequencies are slightly different than commonly stated (63.921 kHz, not 64 kHz)

**PCM (Volume-Only/Forced Output):**
- Set AUDC bit 4 = 1 to enable
- Write 4-bit samples directly to volume bits
- ~4-8 kHz practical sample rates
- Simple but limited quality
- Output is a latched value, not true DC

**PDM (Advanced Techniques):**
- Dual-channel mixing for higher resolution
- Requires 1.79 MHz clocks (AUDCTL bits 5 and 6)
- Needs cycle-perfect timing
- **Achieves 6-7 effective bits** (not true 8-bit due to DAC nonlinearity)
- High quality for demos but CPU-intensive

**Design Philosophy:**
```
PCM = "Good enough" approach
    → Quick to implement
    → Usable during gameplay
    → Recognizable speech/effects

PDM = "Perfectionist" approach  
    → Very complex implementation
    → Requires dedicated CPU time
    → Near-CD quality for demos
    → 6-7 effective bits (not perfect 8-bit)
```

### Further Resources

**Documentation:**
- Original POKEY datasheet (C012294)
- Atari Operating System Manual
- "De Re Atari" Chapter 7 (comprehensive reference)

**Community Resources:**
- AtariAge Forums (8-bit programming section)
- AtariWiki (technical documentation)
- Atari SAP Music Archive (player examples)

**Tools:**
- **RMT** (Raster Music Tracker) - Music composer
- **SAP-R** - Sample converter
- **Altirra** - Accurate emulator for testing

---

## Appendix: Quick Reference Card

### Essential Register Values

```assembly
; Initialize POKEY
LDA #$00 : STA AUDCTL
LDA #$03 : STA SKCTL

; Pure tone (middle C ~262 Hz) with 63.921 kHz clock
LDA #$79 : STA AUDF1   ; Frequency
LDA #$A8 : STA AUDC1   ; Pure tone, volume 8

; 4-bit PCM mode (volume-only/forced output)
LDA #$10 : STA AUDC1   ; Forced output enabled, volume 0
LDA #$1F : STA AUDC1   ; Forced output enabled, volume 15

; 16-bit mode: Channels 1+2 with 1.79 MHz
LDA #$50 : STA AUDCTL  ; Bit 6 (CH1@1.79MHz) + Bit 4 (join 1+2)
; Remember: CH1 = LSB, CH2 = MSB

; 16-bit mode: Channels 3+4 with 1.79 MHz
LDA #$28 : STA AUDCTL  ; Bit 5 (CH3@1.79MHz) + Bit 3 (join 3+4)
; Remember: CH3 = LSB, CH4 = MSB
```

### AUDCTL Bit Quick Reference

```
Bit 7: $80 = 9-bit polynomial (vs 17-bit)
Bit 6: $40 = Channel 1 @ 1.79 MHz
Bit 5: $20 = Channel 3 @ 1.79 MHz
Bit 4: $10 = Join CH1+CH2 (CH1=LSB, CH2=MSB)
Bit 3: $08 = Join CH3+CH4 (CH3=LSB, CH4=MSB)
Bit 2: $04 = High-pass filter CH1 from CH3
Bit 1: $02 = High-pass filter CH2 from CH4
Bit 0: $01 = 15.7 kHz base clock (vs 63.921 kHz)
```

### Frequency Formula

```
For 8-bit channels:
  f_out = f_clock / (2 × (AUDF + 1))

For 16-bit channels (joined):
  N = AUDF_LSB + (AUDF_MSB × 256)
  f_out = f_clock / (2 × (N + 1))

Example for A440 with 1.78977 MHz clock:
  N = (1789770 / (2 × 440)) - 1
  N = 2033.8 - 1 ≈ 2033 = $07F1
  AUDF1 (LSB) = $F1 (241)
  AUDF2 (MSB) = $07 (7)
```

### AUDC Bit Patterns

```
Pure tone:     %10100000 | volume    ; Distortion 5, normal mode
Volume-only:   %00010000 | volume    ; Forced output for PCM
               %11110000 | volume    ; Also works (bits 7-5 ignored)
White noise:   %10000000 | volume    ; 17-bit poly noise
```

### Clock Frequencies (Precise Values)

```
NTSC:
  CPU Clock:    1.789770 MHz (often rounded to 1.79 MHz)
  Base Clock:   63.921 kHz (CPU ÷ 28, often called "64 kHz")
  Alt Clock:    15.700 kHz (CPU ÷ 114, often called "15 kHz")

PAL:
  CPU Clock:    1.773447 MHz (often rounded to 1.77 MHz)
  Base Clock:   63.337 kHz
  Alt Clock:    15.560 kHz
```

