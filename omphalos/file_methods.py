import numpy as np
import pandas as pd
import re
import glob
import pickle


def search_file(dictionary, by_val):
    """Search for CT input file line nums by string. Returns a numpy array of matching line numbers.

    Will search for partial matches at the beginning of the line - e.g. if you wanted to find all the CONDITION
    keywords by you didn't know the name of each keyword block you could search by using 'CONDITION'. You can't
    search from the back, however, so can't find a specific CONDITION block line num by searching for its name.
    """
    keys_list = np.empty(0, dtype=int)
    items_list = dictionary.items()
    for item in items_list:
        # Allow CONDITION or condition since either work in an input file.
        # Can't use by_val.lower() as will erroneously think keywords like 'temperature' are keyword block delimiters.
        if item[1].startswith(by_val.upper()) or item[1].startswith('condition'):
            keys_list = np.append(keys_list, item[0])
    return keys_list


def parse_output(path, output, time_ref):
    """Import the spatial profile output file of the system at the target time specified in the input file. Require
    files to be in the TecPlot format. """
    from pathlib import Path
    file_name = Path(path) / f'{output}{time_ref}.tec'
    # Column headers are quite badly mangled by TecPlot output format. Python csv sniffer will not correctly identify
    # the column headers. So we manually create the correct list by opening the file and navigating to the second
    # line (the header line for TecPlot outputs) and perform some judicious stripping and a regex split to generate
    # the correct list of column headers. We can then pass the header list straight to the read_table method as an
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
            skiprows=[
                0,
                1,
                2],
            names=headers)
        ds = df.to_xarray()
        ds = ds.set_index(index=('X', 'Y', 'Z'))
        ds = ds.unstack('index')

        return ds


def data_cats(path):
    from pathlib import Path

    path = Path(path) / '*.tec'
    f_list = glob.glob(str(path))
    f_list = [i.rstrip('.tec') for i in f_list]
    f_list = [i.rstrip('0123456789') for i in f_list]
    f_list = [i.split('/')[-1] for i in f_list]
    f_set = set(f_list)
    return f_set


def pickle_data_set(data_set, file_name, path_to_file='.'):
    from pathlib import Path

    # Make subdirectory if it doesn't already exist.
    path = Path(path_to_file)
    path.mkdir(exist_ok=True)
    with open(path / file_name, 'wb') as f:
        # Pickle the 'data' dictionary using the highest protocol available.
        pickle.dump(data_set, f, pickle.HIGHEST_PROTOCOL)


def unpickle(file_path):
    from pathlib import Path

    path = Path(file_path)
    with open(path, 'rb') as f:
        # The protocol version used is detected automatically, so we do not
        # have to specify it.
        data = pickle.load(f)
        return data


def dataset_to_netcdf(dataset):
    import xarray as xr
    from omphalos.labels import raw

    for category in dataset[0].results:
        group = raw(dataset, category)

        group.to_netcdf('results.nc', group=category, mode='a')
