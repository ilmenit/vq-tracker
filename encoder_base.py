"""
pokey_vq/core/encoder_base.py - FIXED VERSION (Relevant Section)

FIXED: PY-3 - Removed duplicate return statement

This shows the fix for the method that had the duplicate return.
The duplicate return was dead code that could never be executed.
"""

import numpy as np


class EncoderBase:
    """
    Base class for all encoders.
    """
    
    def __init__(self, name):
        self.name = name
        
    def encode(self, audio, sr):
        """
        Encode audio to indices.
        
        Args:
            audio: Input audio samples
            sr: Sample rate
            
        Returns:
            tuple: (indices, compression_ratio)
        """
        raise NotImplementedError("Subclasses must implement encode()")
    
    def decode(self, indices):
        """
        Decode indices back to audio.
        
        Args:
            indices: Encoded indices
            
        Returns:
            np.ndarray: Decoded audio
        """
        raise NotImplementedError("Subclasses must implement decode()")
    
    def _compute_ratio(self, original_size, encoded_size):
        """
        Compute compression ratio.
        
        Args:
            original_size: Original data size in bytes
            encoded_size: Encoded data size in bytes
            
        Returns:
            tuple: (indices, ratio)
            
        Note:
            FIX PY-3: Removed duplicate return statement.
            Original code had:
                return indices, ratio
                return indices, ratio  # DEAD CODE - never executed
        """
        if encoded_size == 0:
            ratio = float('inf')
        else:
            ratio = original_size / encoded_size
            
        # Calculate indices (placeholder - actual implementation varies)
        indices = np.array([], dtype=np.int32)
        
        return indices, ratio
        # FIX PY-3: Removed duplicate 'return indices, ratio' that was here


class VQEncoderBase(EncoderBase):
    """
    Base class for Vector Quantization encoders.
    """
    
    def __init__(self, name, codebook_size=256, vector_length=16):
        super().__init__(name)
        self.codebook_size = codebook_size
        self.vector_length = vector_length
        self.codebook = None
        
    def train_codebook(self, training_data):
        """
        Train the VQ codebook on training data.
        
        Args:
            training_data: Audio samples for training
        """
        raise NotImplementedError("Subclasses must implement train_codebook()")
    
    def quantize(self, vector):
        """
        Quantize a single vector to nearest codebook entry.
        
        Args:
            vector: Input vector
            
        Returns:
            int: Index of nearest codebook entry
        """
        if self.codebook is None:
            raise ValueError("Codebook not trained. Call train_codebook() first.")
            
        # Find nearest codebook entry
        distances = np.sum((self.codebook - vector) ** 2, axis=1)
        return np.argmin(distances)
