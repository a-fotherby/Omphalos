"""Functions to generate label DataFrames."""


def raw(data_set, output_key):
    """Returns labels DataFrame containing raw CrunchTope output data.
    
    Will return a multi-indexed DataFrame, the level=1 index is the file number, and the level=0 index is a simple
    row count. Spatial data for each input file is stored in a tidy format (tidy taking its technical meaning in
    this case).
    """
    import xarray as xr

    # Generate dataframe of requested labels.
    set_list = []
    for i in data_set:
        set_list.append(data_set[i].results.results_dict[output_key])
    array = xr.concat(set_list, dim='file_num')

    return array


def secondary_precip(dataset):
    """Calculate the total mineral volume evolution over the run by comparing the initial conditions to the final
    mineral volume output.

    Keyword arguments:
    data_set -- The data set to calculate the secondary precipitation for.
    """
    import numpy as np
    import pandas as pd
    import xarray as xr
    import omphalos.spatial_constructor as sc

    # Get DataFrame of output volumes.
    final_vols = raw(dataset, 'volume')
    min_vars = list(final_vols.data_vars)

    coords_array = final_vols.stack(index=('X', 'Y', 'Z'))
    coords_array = coords_array.reset_index(('X', 'Y', 'Z'))
    coords_array = coords_array.reset_coords(('X', 'Y', 'Z'))

    # Create a new DataFrame with the same geometry as the labels by making a deep copy of the coordinate data.
    # Ensure that all the condition blocks have been sorted.
    for i, file in enumerate(dataset):
        file_vols = sc.populate_array(dataset[file], primary_species=False, mineral_vols=True)
        if i == 0:
            shape = tuple((len(dataset), np.shape(file_vols)[0], np.shape(file_vols)[1]))
            initial_vol_array = np.empty(shape)
        initial_vol_array[i, :, :] = file_vols

    fill_value = {var: initial_vol_array[:, :, i] for i, var in enumerate(min_vars)}
    for var in fill_value:
        fill_value.update({var: (['file_num', 'index'], fill_value[var])})
    initial_vols = xr.Dataset(fill_value)
    initial_vols = initial_vols.assign({var: coords_array[var] for var in ('X', 'Y', 'Z')})
    initial_vols = initial_vols.set_index(index=('X', 'Y', 'Z'))
    initial_vols = initial_vols.unstack('index')

    precipitation = final_vols - initial_vols

    return precipitation
