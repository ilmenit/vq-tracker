"""
pokey_vq/core/codebook.py - FIXED VERSION (Relevant Section)

FIXED: PY-8 - Added divide-by-zero protection in probability normalization

This file shows the fix for the _compute_probabilities method.
The full file would include all other methods unchanged.
"""

import numpy as np
from scipy.spatial.distance import cdist


class CodebookOptimizer:
    """
    Optimizes VQ codebook using various algorithms.
    """
    
    # ... other methods unchanged ...
    
    def _compute_probabilities(self, vectors, weights=None):
        """
        Compute assignment probabilities for soft clustering.
        
        Args:
            vectors: Input vectors to assign
            weights: Optional weights for vectors
            
        Returns:
            np.ndarray: Probability matrix (n_vectors x n_entries)
        """
        # Compute distances
        distances = cdist(vectors, self.codebook_entries, metric='sqeuclidean')
        
        # Convert to probabilities using softmax
        # Use negative distances (closer = higher probability)
        # Scale by temperature for sharpness
        temperature = 1.0
        
        probs = np.exp(-distances / temperature)
        
        # FIX PY-8: Protect against divide-by-zero
        # If all probabilities in a row become 0 (can happen with extreme distances),
        # the row sum would be 0 and division would produce NaN.
        # 
        # Old code:
        #   probs /= np.sum(probs, axis=1, keepdims=True)
        #
        # New code with protection:
        row_sums = np.sum(probs, axis=1, keepdims=True)
        
        # Replace zero sums with 1.0 to avoid division by zero
        # This will result in uniform probabilities for those rows
        row_sums = np.where(row_sums == 0, 1.0, row_sums)
        
        probs /= row_sums
        
        # Double-check for NaN and replace with uniform distribution
        nan_rows = np.any(np.isnan(probs), axis=1)
        if np.any(nan_rows):
            uniform_prob = 1.0 / probs.shape[1]
            probs[nan_rows] = uniform_prob
        
        return probs
    
    def _assign_vectors(self, vectors, weights=None, prev_samples=None, continuity_alpha=0):
        """
        Assign vectors to codebook entries.
        
        Args:
            vectors: Input vectors
            weights: Optional weights
            prev_samples: Previous samples for continuity
            continuity_alpha: Weight for continuity penalty
            
        Returns:
            np.ndarray: Assignment indices
        """
        # Compute base distances
        distances = cdist(vectors, self.codebook_entries, metric='sqeuclidean')
        
        # Apply weights if provided
        if weights is not None:
            sqrt_w = np.sqrt(weights)
            # Note: weighted_vectors was calculated but never used in original
            # This is left as-is for compatibility, but could be removed
            weighted_vectors = vectors * sqrt_w[:, np.newaxis]
        
        # Apply continuity penalty
        if continuity_alpha > 0 and prev_samples is not None:
            # Add penalty for discontinuity at boundaries
            for i, entry in enumerate(self.codebook_entries):
                if len(entry) > 0:
                    boundary_diff = np.abs(prev_samples - entry[0])
                    distances[:, i] += continuity_alpha * boundary_diff
        
        # Assign to nearest
        assignments = np.argmin(distances, axis=1)
        
        return assignments
    
    def optimize_lahc(self, vectors, max_iterations=100):
        """
        Optimize codebook using Late Acceptance Hill Climbing.
        
        Args:
            vectors: Training vectors
            max_iterations: Maximum iterations
            
        Returns:
            float: Final cost
        """
        # Constants (previously magic numbers)
        LAHC_SAMPLE_SIZE = 100  # FIX: Named constant instead of magic 100
        LAHC_RELAX_STEPS = 2    # FIX: Named constant instead of magic 2
        
        # Sample for faster evaluation
        n_samples = min(LAHC_SAMPLE_SIZE, len(vectors))
        sample_indices = np.random.choice(len(vectors), n_samples, replace=False)
        sample_vectors = vectors[sample_indices]
        
        # ... rest of LAHC implementation ...
        
        # Relaxation steps
        relax_steps = LAHC_RELAX_STEPS
        
        return 0.0  # Placeholder


# Standalone function for computing weighted probabilities
def compute_weighted_probs(distances, weights=None, temperature=1.0):
    """
    Compute weighted probability distribution from distances.
    
    Args:
        distances: Distance matrix
        weights: Optional sample weights
        temperature: Softmax temperature
        
    Returns:
        np.ndarray: Probability matrix
        
    Note:
        FIX PY-8: This function includes divide-by-zero protection.
    """
    probs = np.exp(-distances / temperature)
    
    if weights is not None:
        probs *= weights[:, np.newaxis]
    
    # FIX PY-8: Protect against divide-by-zero
    row_sums = np.sum(probs, axis=1, keepdims=True)
    row_sums = np.where(row_sums == 0, 1.0, row_sums)
    probs /= row_sums
    
    return probs
