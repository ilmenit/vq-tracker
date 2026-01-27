
import sys
import time
import numpy as np
import logging

# Configure logging
logging.basicConfig(level=logging.DEBUG)

# Add current directory to path
sys.path.append('.')

try:
    from audio_engine import AudioEngine, Channel
    from data_model import Instrument, Song
    import constants
except ImportError as e:
    print(f"Import failed: {e}")
    sys.exit(1)

def test_engine():
    print("Initializing AudioEngine...")
    audio = AudioEngine()
    
    print("Creating test instrument (Sine wave)...")
    inst = Instrument(name="Test Sine")
    sample_rate = 44100
    duration = 1.0
    t = np.linspace(0, duration, int(sample_rate * duration), False)
    # Generate 440Hz sine wave
    data = 0.5 * np.sin(2 * np.pi * 440 * t)
    inst.sample_data = data.astype(np.float32)
    inst.sample_rate = sample_rate
    
    print(f"Instrument loaded: {inst.is_loaded()}, samples={len(inst.sample_data)}")
    
    print("Starting audio engine...")
    if not audio.start():
        print("Failed to start audio engine")
        return
        
    print(f"Audio engine running: {audio.running}")
    
    # Simulate preview_note
    print("Triggering preview note...")
    audio.preview_note(0, 49, inst, 15) # 49 should be middle C approx if base is correct
    
    print("Sleeping for 2 seconds to let it play...")
    time.sleep(2)
    
    print("Stopping audio engine...")
    audio.stop()
    print("Done.")

if __name__ == "__main__":
    test_engine()
