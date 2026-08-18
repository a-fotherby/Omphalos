"""File I/O methods shared across simulator modules."""

import glob
import pickle
import re
from collections.abc import Mapping
from pathlib import Path

import numpy as np
import pandas as pd


class SpilledResults(Mapping):
    """A run's parsed results, held in a netCDF file on disk rather than in memory.

    results.nc is grouped by output category, but the pickles a parallel run leaves behind are per
    run, so collating the sweep has to transpose the two. Holding every run's every category in
    memory to do that costs, for a sweep of 100 runs writing 10 categories of 100 output times over
    1000 cells for 20 species, of order 10 GB.

    Spilling each run's results here as they are read turns that into one netCDF file per run, so the
    collation holds one run plus the one category being written. Each lookup reopens the file and
    returns a fresh Dataset, so mutating what comes back has no effect on what is stored; the
    round trip through netCDF also guarantees numeric dtypes, so the fix_smalls repair does not
    apply to results that have been through it.

    Attributes:
        path: netCDF file holding one group per output category.
    """

    def __init__(self, path, categories):
        """Record where a run's results were spilled to.

        Args:
            path: Path to the netCDF file the results were written to.
            categories: Names of the output categories present in that file.
        """
        self.path = Path(path)
        self._categories = tuple(categories)

    def __getitem__(self, category):
        import xarray as xr

        if category not in self._categories:
            raise KeyError(category)
        return xr.open_dataset(self.path, group=category)

    def __iter__(self):
        return iter(self._categories)

    def __len__(self):
        return len(self._categories)

    def __repr__(self):
        return f'SpilledResults({str(self.path)!r}, {list(self._categories)!r})'


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
        # Take the quoted names, rather than stripping the 'VARIABLES = "' prefix character by
        # character: str.strip removes any of those characters, so a first column named 'SO4--'
        # would lose its leading S.
        headers = re.findall(r'"\s*(.*?)\s*"', headers)

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
    f_list = glob.glob(str(Path(path) / '*.tec'))
    # Take the file name, drop the extension, then drop the trailing output index. Done with stem and
    # a regex rather than rstrip, which strips any of the given characters: 'rate.tec'.rstrip('.tec')
    # is 'ra'.
    f_set = {re.sub(r'\d+$', '', Path(i).stem) for i in f_list}
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


def unique_output_path(name='results.nc', directory=None):
    """Return a path under directory that does not exist yet, numbering the name if it is taken.

    A second sweep run in the same directory writes results1.nc rather than overwriting results.nc,
    a third results2.nc, and so on.

    Args:
        name: Desired file name, e.g. 'results.nc'.
        directory: Directory to place it in (default: the current directory).

    Returns:
        pathlib.Path that did not exist at the time of the call.
    """
    directory = Path(directory) if directory is not None else Path()
    stem = Path(name).stem
    suffix = Path(name).suffix

    path = directory / name
    n = 1
    while path.is_file():
        # If it does exist, mangle name.
        path = directory / f'{stem}{n}{suffix}'
        n += 1

    return path


def matching_output_name(results_path, name='conditions.nc'):
    """Return the file name that pairs with a written results file.

    results.nc pairs with conditions.nc, results1.nc with conditions1.nc, and so on, so that two
    sweeps run in the same directory cannot leave one sweep's results beside another's parameter
    record — which would join silently, both being indexed by run number.

    Args:
        results_path: Path of the results file that was written, or None.
        name: Base name to derive from it.

    Returns:
        str: file name carrying the same numeric suffix as results_path, or name unchanged if
        results_path is None or carries no suffix.
    """
    if results_path is None:
        return name

    match = re.search(r'(\d+)$', Path(results_path).stem)
    if not match:
        return name

    stem = Path(name).stem
    suffix = Path(name).suffix
    return f'{stem}{match.group(1)}{suffix}'


def sanitise_netcdf_names(ds):
    """Return ds with any variable or coordinate name netCDF cannot hold rewritten.

    A '/' is the HDF5 group separator, so netCDF4 refuses it in a name outright rather than escaping
    it. MIN3P emits several ('C-Alk [eq/L]'), which is why a MIN3P results file has to be renamed on
    the way out; a CrunchTope label carrying one would fail identically.

    Applied both when a run's results are spilled to a temporary file and when the results file
    itself is written, so the two agree on what a variable is called.
    """
    renames = {name: name.replace('/', '_per_') for name in list(ds.variables) if '/' in name}

    return ds.rename(renames) if renames else ds


def dataset_to_netcdf(dataset, simulator='crunchtope'):
    """Convert a dataset to netCDF format.

    This function has different behavior depending on the simulator type.

    Args:
        dataset: Dictionary of InputFile objects with results
        simulator: One of 'crunchtope', 'pflotran', or 'min3p'

    Returns:
        For pflotran: the concatenated xarray Dataset.
        For crunchtope/min3p: the Path written, so callers can say where the results went and name
        anything that pairs with them after it.
    """
    import xarray as xr

    # Check that output file doesn't already exist.
    path = unique_output_path('results.nc')

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
                    ds_list.append(_positional_time(sanitise_netcdf_names(results[category])))
                    file_nums.append(getattr(dataset[k], 'file_num', k))
            if not ds_list:
                continue
            try:
                dim = pd.Index(file_nums, name='file_num')
                group = xr.concat(ds_list, dim=dim)
                group.to_netcdf(path, group=category, mode='a')
            except Exception as exc:  # noqa: BLE001 - warn and skip misaligned category
                print(f'WARNING: MIN3P category "{category}" not written to netCDF. ({exc})')
        return path
    else:
        # CrunchTope-style: process by category and write to file
        from coeus.helper import fix_smalls
        from omphalos.labels import raw

        # Take the union of categories across runs. Reading them off the first run alone would drop,
        # for every run, any category that run happened not to produce. Sorted because data_cats
        # discovers them as a set, so the order they were written in — and so the group order of
        # results.nc — varied between otherwise identical sweeps. Matches the MIN3P branch above.
        categories = set()
        for input_file in dataset.values():
            categories.update(input_file.results)
        categories = sorted(categories)

        # Results already spilled to disk have been through a netCDF round trip, which cannot hold
        # the mixed dtypes fix_smalls exists to repair, and reopens on each lookup so its in-place
        # repair would be discarded anyway. compile_results applies it as it spills instead.
        spilled = any(isinstance(f.results, SpilledResults) for f in dataset.values())

        for category in categories:
            if not spilled:
                dataset = fix_smalls(dataset, category)
            group = raw(dataset, category)
            group.to_netcdf(path, group=category, mode='a')
            # Only one category is held at a time, so let this one go before building the next.
            del group

        return path
