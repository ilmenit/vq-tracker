"""
pokey_vq/utils/quality.py - FIXED VERSION

FIXED: PY-5 - Removed duplicate 'import numpy as np'
FIXED: PY-7 - Changed PSNR max_val default from 1.0 to 2.0 for bipolar audio [-1, 1]
"""

import numpy as np
# FIX PY-5: Removed duplicate import (was: import numpy as np twice)
from scipy import signal


def calculate_snr(original, reconstructed):
    """
    Calculate Signal-to-Noise Ratio in dB.
    
    Args:
        original: Original signal
        reconstructed: Reconstructed signal
        
    Returns:
        float: SNR in dB
    """
    # Ensure same length
    min_len = min(len(original), len(reconstructed))
    original = original[:min_len]
    reconstructed = reconstructed[:min_len]
    
    # Calculate signal power
    signal_power = np.mean(original ** 2)
    
    # Calculate noise power
    noise = original - reconstructed
    noise_power = np.mean(noise ** 2)
    
    if noise_power < 1e-10:
        return float('inf')
        
    snr_db = 10 * np.log10(signal_power / noise_power)
    return snr_db


def calculate_psnr(original, reconstructed, max_val=2.0):
    """
    Calculate Peak Signal-to-Noise Ratio in dB.
    
    Args:
        original: Original signal
        reconstructed: Reconstructed signal
        max_val: Maximum possible signal range (peak-to-peak)
        
    Returns:
        float: PSNR in dB
        
    Note:
        FIX PY-7: Changed default max_val from 1.0 to 2.0
        
        For audio normalized to [-1.0, 1.0], the peak-to-peak range is 2.0.
        The old default of 1.0 was only correct for unipolar [0, 1.0] signals,
        which caused PSNR values to be ~6dB lower than they should be.
        
        If your audio is in [0, 1] range, explicitly pass max_val=1.0.
    """
    # Ensure same length
    min_len = min(len(original), len(reconstructed))
    original = original[:min_len]
    reconstructed = reconstructed[:min_len]
    
    # Calculate MSE
    mse = np.mean((original - reconstructed) ** 2)
    
    if mse < 1e-10:
        return float('inf')
        
    psnr_db = 20 * np.log10(max_val / np.sqrt(mse))
    return psnr_db


def calculate_thd(signal_data, sr, fundamental_freq=None):
    """
    Calculate Total Harmonic Distortion.
    
    Args:
        signal_data: Input signal
        sr: Sample rate
        fundamental_freq: Known fundamental frequency (optional)
        
    Returns:
        float: THD as a ratio (0-1)
    """
    # FFT
    n = len(signal_data)
    fft_result = np.fft.rfft(signal_data)
    magnitudes = np.abs(fft_result)
    freqs = np.fft.rfftfreq(n, 1/sr)
    
    # Find fundamental (largest peak)
    if fundamental_freq is None:
        # Skip DC, find max
        fundamental_idx = np.argmax(magnitudes[1:]) + 1
    else:
        fundamental_idx = int(fundamental_freq * n / sr)
        
    fundamental_mag = magnitudes[fundamental_idx]
    
    if fundamental_mag < 1e-10:
        return 0.0
        
    # Sum harmonics (2nd through 10th)
    harmonic_power = 0
    for h in range(2, 11):
        harmonic_idx = fundamental_idx * h
        if harmonic_idx < len(magnitudes):
            harmonic_power += magnitudes[harmonic_idx] ** 2
            
    fundamental_power = fundamental_mag ** 2
    
    thd = np.sqrt(harmonic_power) / np.sqrt(fundamental_power)
    return thd


def calculate_segmental_snr(original, reconstructed, frame_size=256, hop_size=128):
    """
    Calculate Segmental SNR (average SNR over short frames).
    
    More perceptually relevant than global SNR.
    
    Args:
        original: Original signal
        reconstructed: Reconstructed signal
        frame_size: Frame size in samples
        hop_size: Hop size in samples
        
    Returns:
        float: Segmental SNR in dB
    """
    min_len = min(len(original), len(reconstructed))
    original = original[:min_len]
    reconstructed = reconstructed[:min_len]
    
    snrs = []
    
    for start in range(0, min_len - frame_size, hop_size):
        end = start + frame_size
        orig_frame = original[start:end]
        recon_frame = reconstructed[start:end]
        
        signal_power = np.mean(orig_frame ** 2)
        noise_power = np.mean((orig_frame - recon_frame) ** 2)
        
        if signal_power > 1e-10 and noise_power > 1e-10:
            snr = 10 * np.log10(signal_power / noise_power)
            # Clip extreme values
            snr = np.clip(snr, -10, 50)
            snrs.append(snr)
            
    if not snrs:
        return 0.0
        
    return np.mean(snrs)


def calculate_rmse(original, reconstructed):
    """
    Calculate Root Mean Square Error.
    
    Args:
        original: Original signal
        reconstructed: Reconstructed signal
        
    Returns:
        float: RMSE value
    """
    min_len = min(len(original), len(reconstructed))
    original = original[:min_len]
    reconstructed = reconstructed[:min_len]
    
    return np.sqrt(np.mean((original - reconstructed) ** 2))


def calculate_lsd(original, reconstructed, sr=8000):
    """
    Calculate Log Spectral Distance (LSD).
    
    Args:
        original: Original signal
        reconstructed: Reconstructed signal
        sr: Sample rate
        
    Returns:
        float: LSD value
    """
    min_len = min(len(original), len(reconstructed))
    original = original[:min_len]
    reconstructed = reconstructed[:min_len]
    
    # Compute STFT
    f, t, Zxx_orig = signal.stft(original, fs=sr, nperseg=256)
    f, t, Zxx_recon = signal.stft(reconstructed, fs=sr, nperseg=256)
    
    # Log magnitude spectrum
    eps = 1e-10
    log_spec_orig = np.log10(np.abs(Zxx_orig) + eps)
    log_spec_recon = np.log10(np.abs(Zxx_recon) + eps)
    
    # Distance
    dist = np.mean((log_spec_orig - log_spec_recon) ** 2)
    return np.sqrt(dist)


class QualityMetrics:
    """
    Comprehensive quality metrics calculator.
    """
    
    def __init__(self):
        self.metrics = {}
        
    def calculate_all(self, original, reconstructed, sr=8000):
        """
        Calculate all quality metrics.
        
        Args:
            original: Original signal
            reconstructed: Reconstructed signal
            sr: Sample rate
            
        Returns:
            dict: All calculated metrics
        """
        self.metrics = {
            'snr_db': calculate_snr(original, reconstructed),
            'psnr_db': calculate_psnr(original, reconstructed),  # Now uses correct default
            'segmental_snr_db': calculate_segmental_snr(original, reconstructed),
        }
        
        # THD only meaningful for tonal signals
        try:
            self.metrics['thd'] = calculate_thd(reconstructed, sr)
        except:
            self.metrics['thd'] = None
            
        return self.metrics
    
    def report(self):
        """
        Generate formatted report of metrics.
        
        Returns:
            str: Formatted report
        """
        lines = ["Quality Metrics Report", "=" * 30]
        
        for name, value in self.metrics.items():
            if value is None:
                lines.append(f"{name}: N/A")
            elif isinstance(value, float):
                if 'db' in name.lower():
                    lines.append(f"{name}: {value:.2f} dB")
                else:
                    lines.append(f"{name}: {value:.4f}")
            else:
                lines.append(f"{name}: {value}")
                
        return "\n".join(lines)
