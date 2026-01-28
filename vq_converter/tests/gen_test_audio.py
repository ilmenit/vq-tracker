import numpy as np
import scipy.io.wavfile as wavfile

def generate_complex_test_signal(filename, duration=5.0, sample_rate=8000):
    t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
    
    # 1. Sine wave (440 Hz)
    sine = 0.5 * np.sin(2 * np.pi * 440 * t)
    
    # 2. Square wave (220 Hz)
    square = 0.3 * np.sign(np.sin(2 * np.pi * 220 * t))
    
    # 3. White noise burst
    noise = 0.2 * np.random.normal(0, 1, len(t))
    
    # Combine (switch every 1.5 seconds)
    signal = np.zeros_like(t)
    
    idx1 = int(1.5 * sample_rate)
    idx2 = int(3.0 * sample_rate)
    
    signal[:idx1] = sine[:idx1]
    signal[idx1:idx2] = square[idx1:idx2]
    signal[idx2:] = noise[idx2:]
    
    # Normalize to -1..1
    max_val = np.max(np.abs(signal))
    if max_val > 0:
        signal /= max_val
    
    # Convert to 16-bit PCM
    audio_int16 = (signal * 32767).astype(np.int16)
    wavfile.write(filename, sample_rate, audio_int16)
    print(f"Generated {filename}")

if __name__ == "__main__":
    generate_complex_test_signal("tests/test_complex.wav")
