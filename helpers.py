import os
import soundfile as sf
import scipy.signal
import numpy as np

def get_valid_pal_rates():
    """Returns a dict of {divisor: rate_hz} for PAL POKEY."""
    PAL_FREQ = 1773447
    base_clock = PAL_FREQ / 28.0  # ~63337.39 Hz
    rates = {}
    for d in range(256):
        rates[d] = base_clock / (d + 1)
    return rates

def scan_directory_for_audio(path, extensions=None):
    """
    Recursively scan directory for audio files.
    """
    if extensions is None:
        extensions = {'.wav', '.mp3', '.ogg', '.flac', '.aif', '.aiff'}
    
    audio_files = []
    if not os.path.isdir(path):
        print(f"Warning: '{path}' is not a directory.")
        return []
        
    for root, dirs, files in os.walk(path):
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext in extensions:
                audio_files.append(os.path.join(root, f))
    
    # Sort for deterministic order
    audio_files.sort()
    return audio_files


def merge_samples(input_files, target_sr, alignment=1):
    """
    Merge multiple audio files into a single audio array with boundary tracking.
    
    Args:
        input_files: List of audio file paths
        target_sr: Target sample rate (all files resampled to this rate)
        alignment: Pad samples to be multiple of this value (default: 1)
        
    Returns:
        Tuple of (merged_audio, sample_boundaries, sample_names)
        - merged_audio: np.array of all audio concatenated
        - sample_boundaries: List of (start_sample, end_sample) tuples for each file
        - sample_names: List of original filenames (for reference)
    """
    merged = []
    boundaries = []
    names = []
    current_pos = 0
    
    for filepath in input_files:
        print(f"    Loading: {os.path.basename(filepath)}")
        
        try:
            audio, sr = sf.read(filepath)
            # Mix to mono if stereo
            if audio.ndim > 1:
                audio = audio.mean(axis=1)
            audio = audio.astype(np.float32)
            
            # Resample if needed
            if sr != target_sr:
                # Use scipy.signal.resample for resampling
                num_samples = int(len(audio) * target_sr / sr)
                audio = scipy.signal.resample(audio, num_samples)
                print(f"      Resampled {sr} Hz -> {target_sr:.0f} Hz ({len(audio)} samples)")
            else:
                print(f"      {len(audio)} samples at {sr} Hz")
            
            # Pad to alignment (for constant vector length)
            if alignment > 1:
                rem = len(audio) % alignment
                if rem > 0:
                    pad = alignment - rem
                    audio = np.pad(audio, (0, pad))
                    print(f"      Padded +{pad} samples to align to {alignment}")
            
        except Exception as e:
            print(f"    Error loading {filepath}: {e}")
            continue
        
        # Track boundary
        start = current_pos
        end = current_pos + len(audio)
        boundaries.append((start, end))
        names.append(os.path.basename(filepath))
        
        # Append to merged
        merged.append(audio)
        current_pos = end
    
    if not merged:
        return None, [], []
    
    merged_audio = np.concatenate(merged)
    print(f"    Total: {len(merged_audio)} samples ({len(merged_audio)/target_sr:.2f}s) from {len(boundaries)} files")
    
    return merged_audio, boundaries, names
