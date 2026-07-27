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

    Searching for 'CONDITION' is case insensitive, since CrunchTope accepts any
    capitalisation of the keyword and input files in the wild use 'CONDITION',
    'Condition' and 'condition' interchangeably. Every other keyword is matched
    case sensitively: matching 'TEMPERATURE' case insensitively would mistake the
    'temperature' entries inside condition blocks for block delimiters.

    Args:
        dictionary: Dictionary mapping line numbers to line contents
        by_val: String value to search for at the beginning of lines
        allow_white_space: If True, allow leading whitespace before the match

    Returns:
        numpy array of matching line numbers
    """
    prefix = r'\s*' if allow_white_space else ''
    pattern = rf'{prefix}{by_val}(?!_LIST)'
    flags = re.IGNORECASE if by_val.upper() == 'CONDITION' else 0

    # Use list for O(1) appends, then convert to numpy at end
    keys_list = [line_num for line_num, line in dictionary.items()
                 if re.match(pattern, line, flags)]

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
        simulator: One of 'crunchtope', 'pflotran', or 'min3p'

    Returns:
        For pflotran: Returns the concatenated xarray Dataset
        For crunchtope/min3p: Writes to file and returns None
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
    elif simulator == 'min3p':
        # MIN3P-style: each InputFile.results is already a dict of per-category
        # xarray Datasets (dims: output + x/y/z for spatial, or output + time
        # for batch). Concatenate each category over a new 'file_num' dimension
        # and write one netCDF group per category.
        import numpy as np
        import pandas as pd

        def _sanitise_names(ds):
            # netCDF forbids '/' in variable/coord names (it is the HDF5 group
            # separator). MIN3P emits e.g. 'C-Alk [eq/L]'.
            renames = {n: n.replace('/', '_per_') for n in list(ds.variables) if '/' in n}
            return ds.rename(renames) if renames else ds

        def _positional_time(ds):
            # Batch outputs carry an adaptive per-run 'time' axis, so aligning on
            # time values across files would inject NaNs. Concatenate on a
            # positional 'step' index instead, keeping the real times as a
            # (file_num, step) coordinate after concat.
            if 'time' in ds.dims:
                ds = ds.assign_coords(step=('time', np.arange(ds.sizes['time'])))
                ds = ds.swap_dims({'time': 'step'})
            return ds

        keys = sorted(dataset)
        categories = set()
        for k in keys:
            categories.update(dataset[k].results.keys())

        for category in sorted(categories):
            ds_list, file_nums = [], []
            for k in keys:
                results = dataset[k].results
                if category in results:
                    ds_list.append(_positional_time(_sanitise_names(results[category])))
                    file_nums.append(getattr(dataset[k], 'file_num', k))
            if not ds_list:
                continue
            try:
                dim = pd.Index(file_nums, name='file_num')
                group = xr.concat(ds_list, dim=dim)
                group.to_netcdf(path, group=category, mode='a')
            except Exception as exc:  # noqa: BLE001 - warn and skip misaligned category
                print(f'WARNING: MIN3P category "{category}" not written to netCDF. ({exc})')
        return None
    else:
        # CrunchTope-style: process by category and write to file
        from coeus.helper import fix_smalls
        from omphalos.labels import raw

        for category in dataset[next(iter(dataset))].results:
            dataset = fix_smalls(dataset, category)
            group = raw(dataset, category)
            group.to_netcdf(path, group=category, mode='a')
