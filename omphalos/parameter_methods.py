"""Methods for calculating values based on parameters specified in config.yml.

This module re-exports from core.parameter_methods for backward compatibility.
New code should import directly from core.parameter_methods.
"""

# Re-export all functions from core module for backward compatibility
from core.parameter_methods import (
    ParameterConfigError,
    linspace,
    random_uniform,
    constant,
    custom_list,
    fix_ratio,
    staged,
)

__all__ = [
    'ParameterConfigError',
    'linspace',
    'random_uniform',
    'constant',
    'custom_list',
    'fix_ratio',
    'staged',
]
