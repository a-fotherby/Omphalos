
"""Functions to generate label DataFrames."""


#def raw(dataset, output_key):
    #"""Takes a dataset dictionary and returns xr.Dataset for a given category, with the file number as a dimension.
    #"""
    #import xarray as xr
    #import numpy as np

    ## Generate dataframe of requested labels.
    #set_list = []
    #for i in dataset:
        #try:
            #set_list.append(dataset[i].results[output_key])
        #except KeyError:
            #continue
    #array = xr.concat(set_list, dim='file_num')

    #return array

def raw(dataset, output_key):
    """Takes a dataset dictionary and returns an xr.Dataset for a given category,
    with the file number as a dimension. If a KeyError is encountered, 
    it adds a NaN-filled Dataset of the same shape and coordinates as the previous successful one.
    """
    import xarray as xr
    import numpy as np

    set_list = []
    last_coords = None  # To store the coordinates of the last successfully added dataset
    last_dims = None    # To store the dimensions of the last successfully added dataset

    for i in dataset:
        try:
            data = dataset[i].results[output_key]

            # Ensure the data is a Dataset; if it's a DataArray, wrap it in a Dataset
            if isinstance(data, xr.DataArray):
                data = data.to_dataset(name=output_key)

            set_list.append(data)
            last_coords = data.coords  # Store the coordinates of the last valid dataset
            last_dims = data.dims      # Store the dimensions of the last valid dataset
        except KeyError:
            if last_dims is not None and last_coords is not None:
                # Create a NaN-filled Dataset with the same coordinates and dimensions
                nan_data = xr.Dataset(
                    {output_key: (last_dims, np.full(tuple(data.sizes.values()), np.nan))},
                    coords=last_coords
                )
                set_list.append(nan_data)

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
