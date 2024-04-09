"""Plotting scripts for Omphalos-xarray."""


def sum_vars(category_xr, vars, name):
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

    sum_init = category_xr.zeros_like(category_xr.sel(vars[0]))
    category_xr = category_xr.assign({name: sum_init})

    return category_xr


def prod_vars(file, category, vars, name):
    """Product of variables in an Omphalos xarray.
    Modifies the xarray inplace, and creates a new variable {name} along the same dimensions.
    Dimensions of chosen variables must match.
    Can only be used to take product within one output file category.
    ---
    args
        file - omphalos.InputFile()
        category - str, must be one of the output file categories in the file
        vars - list, list of variables to take product of
        name - str, name of the new variable
    ---
    returns:
        file - omphalos.InputFile(), with modified xarray object
    """
    import xarray as xr

    sum_init = xr.ones_like(file.results[category][vars[0]])
    file.results[category] = file.results[category].assign({name: sum_init})

    for var in vars:
        file.results[category][name] *= file.results[category][var]

    return file


def format_axis(axis, font_props, category=None, plot_var=None, column=False):
    """Format an axis plotting Omphalos data in a consistent style."""

    # Style plot
    if column:
        axis.xaxis.tick_top()
        axis.xaxis.set_label_position('top')
        axis.invert_yaxis()
    axis.grid(False)
    axis.tick_params(length=8, width=3)
    for tick in axis.xaxis.get_major_ticks():
        tick.label1.set_fontproperties(font_props)
        tick.label2.set_fontproperties(font_props)
    for tick in axis.yaxis.get_major_ticks():
        tick.label1.set_fontproperties(font_props)
        tick.label2.set_fontproperties(font_props)

    # Thicken spines
    for spine in ['top', 'bottom', 'left', 'right']:
        axis.spines[spine].set_linewidth(3)

    axis.set_ylabel('Depth / m', fontproperties=font_props)
    axis.set_xlabel('', fontproperties=font_props)
    # Set CrunchTope axis labels
    if category == 'totcon':
        axis.set_xlabel(f'[{plot_var}] / mM')
    elif category == 'saturation':
        axis.set_xlabel(f'{plot_var} / $\\mathbf{{\\Omega}}$')
        import numpy as np
        axis.plot(np.zeros(1000), np.arange(1000), ls='--')
        axis.set_xscale('symlog', linthresh=1e-13)
    elif category == 'volume':
        axis.set_xlabel(f'{plot_var} / vol. frac.')
    elif category == 'pH':
        axis.set_xlabel(f'{plot_var}')
    elif category == 'rate':
        axis.set_xlabel(f'{plot_var} precipitation rate / mol s$^{{-1}}$')
        axis.set_xscale('symlog', linthresh=1e-13)
    elif category == None:
        axis.set_ylabel('', fontproperties=font_props)
        pass
    else:
        axis.set_xlabel(f'{plot_var} / UNITS NOT SPECD')

    return axis
