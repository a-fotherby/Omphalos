"""File I/O methods for CrunchTope.

This module re-exports from core.file_methods for backward compatibility.
New code should import directly from core.file_methods.
"""

# Re-export all functions from core module for backward compatibility
from core.file_methods import (
    search_file,
    parse_output,
    data_cats,
    pickle_data_set,
    unpickle,
    dataset_to_netcdf,
)

__all__ = [
    'search_file',
    'parse_output',
    'data_cats',
    'pickle_data_set',
    'unpickle',
    'dataset_to_netcdf',
]
