"""Utilities for working with PFLOTRAN"""

def split_units(string):
    import re

    pattern = r'^(.*?)\s*(\[[^\[\]]+\])$'

    result = re.match(pattern, string)
    try:
        variable = result.group(1)
        unit = result.group(2)
    except AttributeError:
        variable = string
        unit = '-'

    return variable, unit

def extract_numbers(arr):
    import re
    numbers = []
    pattern = r'[-+]?\d*\.\d+E[-+]?\d+|\d+E[-+]?\d+|\d*\.\d+|\d+'  # regex pattern for scientific notation

    for string in arr:
        match = re.search(pattern, string)
        if match:
            numbers.append(float(match.group()))

    return numbers


def h5_to_xarray(file):
    """ Method to convert h5 file to xarray. Specific to PFLOTRAN output.
    :param file: h5 file object
    :return: xarray.DataArray
    """
    import copy
    import xarray as xr
    try:
        file['Provenance']['PFLOTRAN']
    except KeyError:
        print("Are you this is a PFLOTRAN file?")

    # Get keys for time snapshots
    keys = file.keys()
    values_to_remove = ['Coordinates', 'Provenance']
    snapshot_keys = [x for x in keys if x not in values_to_remove]
    # Convert snapshot key names to time steps
    times = sorted(extract_numbers(snapshot_keys))

    # Get dataset shape
    time_dim_length = len(snapshot_keys)
    dim_lengths = {}
    # Match direction and dimension key from the file.
    # Done via and assumed order for now but could be improved to RegEx matching if required.
    dim_direction = dict(zip(['x','y','z'], list(file['Coordinates'].keys())))

    for direction in dim_direction:
        dim_lengths.update({direction: len(file['Coordinates'][dim_direction[direction]]) - 1})
    dim_lengths.update({'time': len(snapshot_keys)})

    da = xr.DataArray()
    # Add dimensions
    da = da.expand_dims(dim=dim_lengths)
    # Add coordinates
    # Need to convert to 'point' rather than block format, so must get offset array
    # Assume grid is regular
    coordinates_dict = {}
    coord_units_dict = {}
    for coord in dim_direction:
        # Since grid is regular, remove last element and offset values by 1/2 interval
        arr = file['Coordinates'][dim_direction[coord]][:]
        grid_step = arr[1] - arr[0]
        arr = arr[:-1]
        arr = arr + grid_step/2
        # Split direction name and units before assignment
        dir_name, units = split_units(dim_direction[coord])
        coordinates_dict.update({dir_name: (coord, arr)})
        coord_units_dict.update({dir_name: units})
    # Assign coordinates to dimensions
    da = da.assign_coords(coordinates_dict)
    da = da.assign_coords(time = ('time', times))
    for coord in coord_units_dict:
        da.coords[coord].attrs['units'] = coord_units_dict[coord]
    # Time unit is last letter in time index key string
    da.coords['time'].attrs['units'] = snapshot_keys[0][-1]

    ds = xr.Dataset()
    # Now dimensionality and coordinates have been constructed, populate with data
    for variable in file[snapshot_keys[0]].keys():
        name, unit = split_units(variable)
        da_var = copy.deepcopy(da)
        for i, time in enumerate(snapshot_keys):
            da_var[:,:,:,i] = file[snapshot_keys[i]][variable]
            da_var.attrs['units'] = unit
        ds[name] = da_var

    return ds