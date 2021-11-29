"""Methods for calculating values based on parameters specified in config.yaml"""


def linspace(lower, upper, number_of_files, file_num, *, interval_to_step=1):
    """Return value in linear spacing by file number.
    
    Args: lower -- lower bound of range. upper -- upper bound of range. number_of_files -- number of files in
    Omphalos run. file_num -- the file number of this specific input file. interval_to_step -- number of steps over
    which to hold a specific value. E.g. if you wanted to change a concentration every 3 input files instead of every
    1 input file you would make this 3. For example, on the range 1-10 for 10 input files: [1 1 1 3 3 3 7 7 7 10].
    """
    step_size = (upper - lower) / (number_of_files / interval_to_step)
    step_num = file_num // interval_to_step
    linearly_spaced_var = (step_size * step_num) + lower
    return linearly_spaced_var
