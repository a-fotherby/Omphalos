"""Methods for constructing tidy DataFrames of geochemical data.

This module re-exports from core.spatial_constructor for backward compatibility.
New code should import directly from core.spatial_constructor.
"""

# Re-export all functions from core module for backward compatibility
from core.spatial_constructor import (
    populate_array,
    initialise_array,
    compute_rows,
)

__all__ = [
    'populate_array',
    'initialise_array',
    'compute_rows',
]
