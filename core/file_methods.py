"""File I/O methods shared across simulator modules."""

import csv
import glob
import pickle
import re
import warnings
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


# The X, Y and Z columns every TecPlot spatial output opens with. An unnamed column belongs after
# them, never before, so this is where reconstructed names are inserted.
COORDINATE_COLUMNS = 3


def reconcile_headers(headers, width, leading_names=()):
    """Return a header list as wide as the data, naming any column the file declared no name for.

    CrunchTope's `surface` output writes more columns than it names. `GraphicsVisit.F90` builds the
    VARIABLES line over `ns = 1, nsurf_sec` -- the secondary surface complexes -- and then writes the
    data over `ns = 1, nsurf + nsurf_sec`, which is the free sites *followed by* those complexes. The
    file therefore carries `nsurf` unnamed columns, and because they come first, every name in the
    header sits two columns to the left of the values it describes: read at face value, the site
    concentration is reported as the first complex, and so on to the end of the row.

    Nothing in the file says so, and pandas makes it worse: given fewer names than columns it
    promotes the surplus to a MultiIndex rather than complaining, and the ValueError that eventually
    surfaces ('PandasMultiIndex only accepts 1-dimensional variables') points nowhere near the cause.

    Args:
        headers: The names the file declared, X/Y/Z first.
        width: How many columns the data actually has.
        leading_names: Names for the unnamed columns, in file order, where the caller knows them --
            for `surface` output, the deck's SURFACE_COMPLEXATION sites. Used only if there are
            exactly as many as are missing; otherwise placeholders are substituted, which still puts
            the declared names back on their own columns.

    Returns:
        A list of names as long as the data is wide.
    """
    missing = width - len(headers)

    if missing <= 0:
        return list(headers)

    names = list(leading_names)

    if len(names) != missing:
        names = [f'unnamed_{index + 1}' for index in range(missing)]
        warnings.warn(
            f'{output_description(headers)}: the file declares {len(headers)} column names for '
            f'{width} columns of data. The {missing} unnamed column(s) have been called {names} and '
            f'placed after X/Y/Z, which is where CrunchTope writes them.'
        )

    return list(headers[:COORDINATE_COLUMNS]) + names + list(headers[COORDINATE_COLUMNS:])


def output_description(headers):
    """A short description of an output file for a warning message."""
    named = [name for name in headers[COORDINATE_COLUMNS:]][:3]

    return f'TecPlot output carrying {named}...' if named else 'TecPlot output'


def data_width(file_name, skip):
    """Return how many whitespace-separated fields the first data row of a TecPlot file has."""
    with open(file_name) as file:
        for index, line in enumerate(file):
            if index < skip:
                continue
            if line.strip():
                return len(line.split())

    return 0


# A value whose exponent needs three digits, written without the 'E' that belongs before it, because
# the number overran its Fortran output field: '1.2345-100' for 1.2345E-100. Anchored at the end of the
# token and requiring at least two exponent digits, so a well-formed '1.234e-05' -- where the sign
# follows a letter rather than a digit -- cannot match.
MALFORMED_EXPONENT = re.compile(r'(\d)([-+])(\d{2,})$')


def repair_exponents(values):
    """Put the 'E' back into values CrunchTope wrote without one.

    The alternative, and what this used to do, was to substitute zero. The magnitudes involved are
    below 1e-100 so the numerical difference is nil, but a repaired value is still the number the
    model produced, and a column of them no longer reads as a column of exact zeros.

    Args:
        values: A pandas Series or xarray DataArray of strings.

    Returns:
        The same object with the exponents repaired.
    """
    return values.str.replace(MALFORMED_EXPONENT.pattern, r'\1e\2\3', regex=True)


def parse_time_series(path, file_name):
    """Import a CrunchTope time-series output file.

    This is the only CrunchTope output written per timestep rather than per snapshot, which makes it
    the way to see a transient: a `spatial_profile` list resolves whatever times the deck author
    thought to ask for and nothing between them.

    The time axis is the run's own timestepping, so two runs of one sweep do not share it and need not
    even be the same length. The dimension is therefore a positional `step` with the real times
    carried as a coordinate on it, which is what lets runs concatenate without either inventing values
    at times a run never reached or interleaving NaN at every time it did not share.

    Args:
        path: Path to the directory containing the file.
        file_name: Name of the time-series file, as the deck's OUTPUT block gives it.

    Returns:
        xarray Dataset indexed on 'step', with 'time' as a coordinate on it.
    """
    import xarray as xr

    full_path = Path(path) / file_name

    with open(full_path) as file:
        file.readline()                       # '# Time series at grid cell: ...'
        header_line = file.readline()

    # The header is a TecPlot VARIABLES line, and CrunchTope truncates it: the Ex5 deck's ends on a
    # bare opening quote. Taking the quoted runs rather than splitting on commas ignores the stub.
    headers = [name.strip() for name in re.findall(r'"([^"]*)"', header_line)]
    headers = [netcdf_name(name) for name in headers if name.strip()]

    # A column the header does not name belongs at the END here, not after the third one. A time
    # series has no X/Y/Z to insert behind -- its first column is the time -- so reconcile_headers,
    # which is written for spatial output, would put a placeholder at column 3 and shift every name
    # after it onto the wrong data. What CrunchTope actually writes unnamed is a trailing field, and
    # in Ex8's and Ex9's files it is identically zero at every timestep.
    width = data_width(full_path, skip=2)
    if width > len(headers):
        headers += [f'unnamed_{index + 1}' for index in range(width - len(headers))]
    elif width < len(headers):
        headers = headers[:width]

    frame = pd.read_csv(full_path, sep=r'\s+', skipinitialspace=True, skiprows=[0, 1],
                        names=headers, quoting=csv.QUOTE_NONE)

    for column in frame:
        if frame[column].dtype == object:
            frame[column] = repair_exponents(frame[column].astype(str)).astype(float)

    # The first column is the time, whatever the deck's time_units called it.
    time_column = headers[0]
    dataset = xr.Dataset(
        {name: ('step', frame[name].to_numpy()) for name in headers[1:]},
        coords={'step': np.arange(len(frame)), 'time': ('step', frame[time_column].to_numpy())},
    )
    dataset['time'].attrs['long_name'] = time_column

    return dataset


def parse_output(path, output, time_ref, leading_names=()):
    """Import the spatial profile output file of the system at the target time.

    Requires files to be in the TecPlot format.

    Args:
        path: Path to the directory containing output files
        output: Name of the output file (without time suffix)
        time_ref: Time reference number for the output file
        leading_names: Names for columns the file writes but does not declare, in file order. See
            :func:`reconcile_headers`, which is only reached by CrunchTope's `surface` output.

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
        # Made as wide as the data before reading, so pandas is never left to decide what to do with
        # a column it has no name for.
        headers = reconcile_headers(headers, data_width(file_name, skip=3), leading_names)

        df = pd.read_table(
            file_name,
            sep=r'\s+',
            skipinitialspace=True,
            skiprows=[0, 1, 2],
            names=headers,
            # Quoting off. The header line is the only quoted thing in the file and it is skipped, but
            # CrunchTope can truncate it mid-quote -- the time series files do -- and an unclosed quote
            # makes the C parser read the whole remaining file as one string field. With names given
            # that returns zero rows rather than raising, so the failure is silent.
            quoting=csv.QUOTE_NONE,
        )
        ds = df.to_xarray()

        # A column that came back as object rather than float holds at least one value CrunchTope
        # wrote in a form Fortran cannot read back. Repair it. If that is not what is wrong, the
        # astype below raises and is caught by the try-except this is called inside.
        for variable in ds:
            if ds[variable].dtype == object:
                ds[variable] = repair_exponents(ds[variable].astype(str)).astype(float)

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


def netcdf_name(name):
    """Return a name netCDF will accept, changing as little as possible.

    Two rules, both established by trying them against the library rather than read off it:

    * A '/' is the HDF5 group separator, so it cannot appear anywhere. MIN3P emits several
      ('C-Alk [eq/L]').
    * The *first* character must be alphanumeric or an underscore. Later characters are far more
      permissive -- 'X>FeO' and 'Ca++' are both fine -- so only the leading one needs a prefix.
      CrunchTope names every surface complex with a leading '>' ('>FeO-_str'), which is what makes
      this reachable at all.
    """
    name = str(name).replace('/', '_per_')

    if name and not (name[0].isalnum() or name[0] == '_'):
        name = f'_{name}'

    return name


def sanitise_netcdf_names(ds):
    """Return ds with any variable or coordinate name netCDF cannot hold rewritten.

    Applied both when a run's results are spilled to a temporary file and when the results file
    itself is written, so the two agree on what a variable is called.
    """
    renames = {name: netcdf_name(name) for name in list(ds.variables)}
    renames = {old: new for old, new in renames.items() if old != new}

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
                ds = xr.concat([ds, dataset[key].results], dim='file_num', join='outer')
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
                # join='outer' is the current default, stated because xarray is changing it
                # to 'exact'. MIN3P runs take their own number of timesteps, so `step` never
                # matches across a sweep; under 'exact' this raises, and the except below
                # would swallow it and drop the category from results.nc without failing.
                dim = pd.Index(file_nums, name='file_num')
                group = xr.concat(ds_list, dim=dim, join='outer')
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
            # Results that were spilled have already been through this; results held in memory --
            # the sequential omphalos path -- have not, and a surface complex would stop the write.
            group = sanitise_netcdf_names(group)
            group.to_netcdf(path, group=category, mode='a')
            # Only one category is held at a time, so let this one go before building the next.
            del group

        return path
