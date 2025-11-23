"""Functions for generating DataFrames of attributes from simulation datasets.

This module re-exports from core.attributes for backward compatibility.
New code should import directly from core.attributes.
"""

# Re-export all functions from core module for backward compatibility
from core.attributes import (
    get_condition,
    boundary_condition,
    mineral_volume,
    primary_species,
    initial_conditions,
    mineral_rates,
    aqueous_rates,
    normalise_by_frac,
)

__all__ = [
    'get_condition',
    'boundary_condition',
    'mineral_volume',
    'primary_species',
    'initial_conditions',
    'mineral_rates',
    'aqueous_rates',
    'normalise_by_frac',
]
