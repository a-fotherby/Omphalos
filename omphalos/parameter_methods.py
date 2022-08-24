"""Methods for calculating values based on parameters specified in config.yml. In each case, params is a list
containing numeric information required to generate the array, as specified in the config documentation. """


def linspace(params, num_files):
    """Return value in linear spacing by file number.
    
    Args: lower -- lower bound of range. upper -- upper bound of range. number_of_files -- number of files in
    Omphalos run.

    E.g. if you wanted to change a concentration every 3 input files instead of every 1 input file you would make
    this 3. For example, on the range 1-10 for 12 input files: [1, 1, 1, 4, 4, 4, 7, 7, 7, 10, 10, 10].

    Important: repeats must be a factor of num_files or an exception will be thrown.
    """
    import numpy as np

    lower = params[0]
    upper = params[1]

    # Look for repeat param:
    try:
        repeats = params[2]
    except IndexError:
        repeats = 1

    if num_files % repeats != 0:
        Exception('In specifying a linspace change, repeats is not a factor of the number of files. Abort.')
        import sys
        sys.exit()
    else:
        # Number of points in linspace before repeats.
        points = num_files // repeats

    array = np.linspace(lower, upper, points)
    # Repeat entries if required, otherwise returns original array.
    array = np.repeat(array, repeats)

    return array


def random_uniform(params, num_files):
    import numpy as np
    lower = params[0]
    upper = params[1]
    array = np.random.uniform(lower, upper, num_files)

    return array


def constant(params, num_files):
    import numpy as np
    array = np.ones(num_files) * params

    return array


def custom_list(params, num_files):
    array = params

    return array


def fix_ratio(to_change, num_files, ref_vars):
    import omphalos.keyword_block as kwb
    reference_var = to_change[1]
    # Catch extra subscript indexing required for KeywordBlock.
    # This dict comparison is definitely a bad hack. Fix later.
    if type(ref_vars) == dict:
        reference_value = float(ref_vars[reference_var][-1])
    elif type(ref_vars) == kwb.KeywordBlock:
        reference_value = float(ref_vars.contents[reference_var][-1])
    else:
        reference_value = None
        Exception(f'You have somehow referenced a block object of unknown type. Abort.')
        import sys
        sys.exit()
    multiplier = to_change[2]
    value = reference_value * multiplier

    return value
