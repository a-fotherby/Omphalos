"""Plotting scripts for Omphalos-xarray."""


def sum_vars(file, category, vars, name):
    """Sum variables in an Omphalos xarray.
    Modifies the xarray inplace, and creates a new variable {name} along the same dimensions.
    Dimensions of chosen variables must match.
    Can only be used to sum within one output file category.
    ---
    args
        file - omphalos.InputFile()
        category - str, must be one of the output file categories in the passed file
        vars - list, list of variables to sum
        name - str, name of the new variable
    ---
    returns:
        file - omphalos.InputFile(), with modified xarray object
    """
    import xarray as xr

    sum_init = xr.zeros_like(file.results[category][vars[0]])
    file.results[category] = file.results[category].assign({name: sum_init})

    for var in vars:
        file.results[category][name] += file.results[category][var]

    return file
