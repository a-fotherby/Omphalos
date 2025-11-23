"""Core shared modules for Omphalos.

This module contains shared functionality used by both the omphalos (CrunchTope)
and pflotran simulators to avoid code duplication.

Submodules:
    - parameter_methods: Methods for generating parameter value arrays
    - attributes: Functions for extracting DataFrames from simulation datasets
    - spatial_constructor: Methods for constructing spatial arrays
    - file_methods: File I/O utilities
    - keyword_block: Keyword block object classes
"""

# Lazy imports - submodules can be imported directly as needed
# e.g., from core import parameter_methods
# or: from core.parameter_methods import linspace
