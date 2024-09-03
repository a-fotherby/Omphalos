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
    import xarray as xr
    import numpy as np
    import re

    # Specify the path to your .h5 file

    # Initialize dictionaries to hold the data variables and coordinates
    data_vars = {}
    coords = {}

    # Open the .h5 file using h5py
    # Extract coordinates from the 'Coordinates' group and compute cell-centered coordinates
    for coord_name in file['Coordinates']:
        boundary_coords = file['Coordinates'][coord_name][:]
        cell_center_coords = (boundary_coords[:-1] + boundary_coords[1:]) / 2
        coords[coord_name] = cell_center_coords
    
    # Identify all time groups (assuming they start with 'Time')
    time_groups = [key for key in file.keys() if key.startswith('Time:')]
    time_points = []
    all_data = {}

    # Iterate over each time group to extract data
    for time_group in time_groups:
        # Extract the time value from the group name
        time_value = float(time_group.split(':')[1].strip().split()[0])
        time_points.append(time_value)
        
        # Extract data for each variable within the time group
        for data_name in file[time_group]:
            if data_name not in all_data:
                all_data[data_name] = []
            all_data[data_name].append(file[time_group][data_name][:])

    # Sort time points and reorder data accordingly
    sorted_indices = np.argsort(time_points)
    sorted_time_points = np.array(time_points)[sorted_indices]

    # Convert lists to numpy arrays and sort them by time
    for data_name in all_data:
        data_array = np.array(all_data[data_name])
        all_data[data_name] = data_array[sorted_indices]
    
    # Add data variables to the xarray dataset, organized by the 'time' dimension
    for data_name, data_array in all_data.items():
        # Use regex to separate the variable name and units
        match = re.match(r"(.+?)\s*\[(.+?)\]", data_name)
        if match:
            var_name, units = match.groups()
        else:
            var_name, units = data_name, None
        
        # Add variable data and units to the dataset
        data_vars[var_name] = (['time', 'x', 'y', 'z'], data_array, {'units': units})

    # Create an xarray Dataset
    ds = xr.Dataset(
        data_vars=data_vars,
        coords={
            'time': sorted_time_points,
            'x': coords['X [m]'],
            'y': coords['Y [m]'],
            'z': coords['Z [m]']
        }
    )

    return ds
