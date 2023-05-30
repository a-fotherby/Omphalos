
"""Functions to generate label DataFrames."""


def raw(dataset, output_key):
    """Takes a dataset dictionary and returns xr.Dataset for a given category, with the file number as a dimension.
    """
    import xarray as xr

    # Generate dataframe of requested labels.
    set_list = []
    for i in dataset:
        set_list.append(dataset[i].results[output_key])
    array = xr.concat(set_list, dim='file_num')

    return array


def secondary_precip(dataset):
    """Calculate the total mineral volume evolution over the run by comparing the initial conditions to the final
    mineral volume output.

    Keyword arguments:
    data_set -- The data set to calculate the secondary precipitation for.
    """
    from omphalos import attributes as attr

    # Get DataFrame of output volumes.
    final_vols = raw(dataset, 'volume')

    initial_vols = attr.initial_conditions(dataset, concentrations=False, minerals=True)

    precipitation = final_vols - initial_vols

    return precipitation
