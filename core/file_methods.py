"""File I/O methods shared across simulator modules."""

import glob
import pickle
import re
from pathlib import Path

import numpy as np
import pandas as pd


def search_file(dictionary, by_val, allow_white_space=True):
    """Search for input file line numbers by string.

    Returns a numpy array of matching line numbers. Will search for partial
    matches at the beginning of the line - e.g. if you wanted to find all the
    CONDITION keywords but you didn't know the name of each keyword block you
    could search by using 'CONDITION'. You can't search from the back, however,
    so can't find a specific CONDITION block line num by searching for its name.

    Args:
        dictionary: Dictionary mapping line numbers to line contents
        by_val: String value to search for at the beginning of lines
        allow_white_space: If True, allow leading whitespace before the match

    Returns:
        numpy array of matching line numbers
    """
    # Use list for O(1) appends, then convert to numpy at end
    keys_list = []
    items_list = dictionary.items()

    for item in items_list:
        # Allow CONDITION or condition since either work in an input file.
        # Can't use by_val.lower() as will erroneously think keywords like
        # 'temperature' are keyword block delimiters.
        if allow_white_space:
            pattern = rf'\s*{by_val}(?!_LIST)'
        else:
            pattern = rf'{by_val}(?!_LIST)'

        if re.match(pattern, item[1]) or item[1].startswith('condition'):
            keys_list.append(item[0])

    return np.array(keys_list, dtype=int)


def parse_output(path, output, time_ref):
    """Import the spatial profile output file of the system at the target time.

    Requires files to be in the TecPlot format.

    Args:
        path: Path to the directory containing output files
        output: Name of the output file (without time suffix)
        time_ref: Time reference number for the output file

    Returns:
        xarray Dataset with parsed output data
    """
    file_name = Path(path) / f'{output}{time_ref}.tec'

    # Column headers are quite badly mangled by TecPlot output format. Python
    # csv sniffer will not correctly identify the column headers. So we manually
    # create the correct list by opening the file and navigating to the second
    # line (the header line for TecPlot outputs) and perform some judicious
    # stripping and a regex split to generate the correct list of column headers.
    # We can then pass the header list straight to the read_table method as an
    # override.
    with open(file_name) as f:
        f.readline()
        headers = f.readline()
        headers = headers.strip('VARIABLES = "')
        headers = headers.rstrip('" \n')
        headers = re.split(r'"\s+"', headers)

        df = pd.read_table(
            file_name,
            sep=r'\s+',
            skipinitialspace=True,
            skiprows=[0, 1, 2],
            names=headers
        )
        ds = df.to_xarray()

        # Check for any variables that have been parsed that are not floats.
        # Any that are mixed datatypes are likely due to CT scientific notation
        # for values less than 1e-100. Replace and fix. If not the problem,
        # an error should be thrown and caught in the try-except in which this
        # is called.
        for variable in ds:
            if ds[variable].dtype == object:
                ds[variable] = ds[variable].astype(str).str.replace(r'\d.\d+-\d+', '0', regex=True).astype(float)

        ds = ds.set_index(index=('X', 'Y', 'Z'))
        ds = ds.unstack('index')

        return ds


def data_cats(path):
    """Get the set of data categories (output types) from TecPlot files in a directory.

    Args:
        path: Path to the directory containing .tec files

    Returns:
        Set of unique category names
    """
    path = Path(path) / '*.tec'
    f_list = glob.glob(str(path))
    f_list = [i.rstrip('.tec') for i in f_list]
    f_list = [i.rstrip('0123456789') for i in f_list]
    f_list = [i.split('/')[-1] for i in f_list]
    f_set = set(f_list)
    return f_set


def pickle_data_set(data_set, file_name, path_to_file='.'):
    """Pickle a dataset to a file.

    Args:
        data_set: The data to pickle
        file_name: Name of the pickle file
        path_to_file: Directory to save to (default: current directory)
    """
    # Make subdirectory if it doesn't already exist.
    path = Path(path_to_file)
    path.mkdir(exist_ok=True)
    with open(path / file_name, 'wb') as f:
        # Pickle the 'data' dictionary using the highest protocol available.
        pickle.dump(data_set, f, pickle.HIGHEST_PROTOCOL)


def unpickle(file_path):
    """Load a pickled dataset from a file.

    Args:
        file_path: Path to the pickle file

    Returns:
        The unpickled data
    """
    path = Path(file_path)
    with open(path, 'rb') as f:
        # The protocol version used is detected automatically, so we do not
        # have to specify it.
        data = pickle.load(f)
        return data


def dataset_to_netcdf(dataset, simulator='crunchtope'):
    """Convert a dataset to netCDF format.

    This function has different behavior depending on the simulator type.

    Args:
        dataset: Dictionary of InputFile objects with results
        simulator: Either 'crunchtope' or 'pflotran'

    Returns:
        For pflotran: Returns the concatenated xarray Dataset
        For crunchtope: Writes to file and returns None
    """
    import xarray as xr
    import pathlib as pl

    # Check that output file doesn't already exist.
    path = pl.Path() / 'results.nc'
    n = 1
    while True:
        if path.is_file():
            # If it does exist, mangle name.
            path = pl.Path() / f'results{n}.nc'
            n += 1
        else:
            break

    if simulator == 'pflotran':
        # PFLOTRAN-style: concatenate all results and return
        ds = dataset[0].results
        for key in dataset:
            if key == 0:
                continue
            else:
                ds = xr.concat([ds, dataset[key].results], dim='file_num')
        return ds
    else:
        # CrunchTope-style: process by category and write to file
        from coeus.helper import fix_smalls
        from omphalos.labels import raw

        for category in dataset[next(iter(dataset))].results:
            dataset = fix_smalls(dataset, category)
            group = raw(dataset, category)
            group.to_netcdf(path, group=category, mode='a')
