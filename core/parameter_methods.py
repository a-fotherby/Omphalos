"""Methods for calculating values based on parameters specified in config.yml.

In each case, params is a list containing numeric information required to generate
the array, as specified in the config documentation.
"""

import numpy as np


class ParameterConfigError(Exception):
    """Exception raised for errors in parameter configuration."""
    pass


def linspace(params, num_files):
    """Return value in linear spacing by file number.

    Args:
        params: List containing [lower, upper] or [lower, upper, repeats]
            - lower: lower bound of range
            - upper: upper bound of range
            - repeats: (optional) number of times to repeat each value
        num_files: number of files in the run

    Returns:
        numpy array of linearly spaced values

    Raises:
        ParameterConfigError: If repeats is not a factor of num_files

    Example:
        If you wanted to change a concentration every 3 input files instead of
        every 1 input file you would make repeats=3. For example, on the range
        1-10 for 12 input files: [1, 1, 1, 4, 4, 4, 7, 7, 7, 10, 10, 10].
    """
    lower = params[0]
    upper = params[1]

    # Look for repeat param:
    try:
        repeats = params[2]
    except IndexError:
        repeats = 1

    if num_files % repeats != 0:
        raise ParameterConfigError(
            f'In specifying a linspace change, repeats ({repeats}) is not a factor '
            f'of the number of files ({num_files}). Abort.'
        )

    # Number of points in linspace before repeats.
    points = num_files // repeats

    array = np.linspace(lower, upper, points)
    # Repeat entries if required, otherwise returns original array.
    array = np.repeat(array, repeats)

    return array


def random_uniform(params, num_files):
    """Generate random values from a uniform distribution.

    Args:
        params: List containing [lower, upper] bounds for the uniform distribution
        num_files: number of values to generate

    Returns:
        numpy array of random values
    """
    lower = params[0]
    upper = params[1]
    array = np.random.uniform(lower, upper, num_files)

    return array


def constant(params, num_files):
    """Generate an array of constant values.

    Args:
        params: The constant value to use
        num_files: number of values to generate

    Returns:
        numpy array of constant values
    """
    array = np.ones(num_files) * params

    return array


def custom_list(params, num_files):
    """Use a custom list of values.

    Args:
        params: List of values to use directly
        num_files: number of files (unused, but kept for consistent interface)

    Returns:
        The input params list
    """
    return params


def fix_ratio(to_change, num_files, ref_vars):
    """Fix a value as a ratio of another parameter.

    Args:
        to_change: List containing [_, reference_var, multiplier]
        num_files: number of files (unused, but kept for consistent interface)
        ref_vars: The reference variables dictionary or KeywordBlock

    Returns:
        The calculated value (reference_value * multiplier)

    Raises:
        ParameterConfigError: If ref_vars is of unknown type
    """
    from core.keyword_block import KeywordBlock

    reference_var = to_change[1]

    # Catch extra subscript indexing required for KeywordBlock.
    if isinstance(ref_vars, dict):
        reference_value = float(ref_vars[reference_var][-1])
    elif isinstance(ref_vars, KeywordBlock):
        reference_value = float(ref_vars.contents[reference_var][-1])
    else:
        raise ParameterConfigError(
            f'You have referenced a block object of unknown type: {type(ref_vars)}. Abort.'
        )

    multiplier = to_change[2]
    value = reference_value * multiplier

    return value


def staged(params, num_files, stage_num=None):
    """Return constant value for all runs at a specific stage.

    Used for staged restart runs where parameters vary across sequential
    stages within each parallel run.

    Args:
        params: List of values, one per stage.
        num_files: Number of parallel runs.
        stage_num: The current stage index (0-indexed).

    Returns:
        numpy array of length num_files with the value for the current stage.

    Raises:
        ParameterConfigError: If stage_num is not provided.
    """
    if stage_num is None:
        raise ParameterConfigError("staged() requires stage_num parameter")
    value = params[stage_num]
    return np.ones(num_files) * value
