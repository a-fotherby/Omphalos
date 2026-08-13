"""Omphalos analysis helper functions."""


def quick_import(path, smalls_cats=None):
    """Load a pickled InputFile dictionary and drop the runs that failed.

    Args:
        path: Path to the pickle written by omphalos/main.py.
        smalls_cats: Unused. Retained for call compatibility.

    Returns:
        dict of InputFile objects that ran cleanly, keyed by run number.
    """
    from omphalos import file_methods as fm

    raw = fm.unpickle(path)
    dataset, errors = filter_errors(raw)

    return dataset


def filter_errors(dataset, verbose=False):
    """Split a dataset into the runs that succeeded and the runs that failed.

    A run fails by carrying a non-zero error_code, set by the simulator wrapper: 1 is a timeout,
    higher values are the error patterns matched in the simulator's output (see CT_ERROR_PATTERNS in
    omphalos/run.py), and -1 means the simulator exited without writing any output.

    The input dictionary is left untouched; both returned dictionaries are new, and keyed by run
    number so they stay aligned with results.nc.

    Note there is no check here for runs that returned no output at all. omphalos/main.py deletes
    InputFile.results before pickling, since the results themselves live in results.nc, so an absent
    or empty results dict is normal in inputs.pkl rather than a sign of failure.

    Args:
        dataset: dict of InputFile objects, keyed by run number.
        verbose: Whether to list the run numbers that failed, with their error codes.

    Returns:
        (clean, errors): two dicts of InputFile objects, keyed by run number.
    """
    clean = {}
    errors = {}

    for i, input_file in dataset.items():
        if getattr(input_file, 'error_code', 0) != 0:
            errors[i] = input_file
        else:
            clean[i] = input_file

    total = len(dataset)
    rate = len(errors) / total * 100 if total > 0 else 0.0

    print(f'Returned {len(clean)} files without errors out of a total possible {total}.')
    print(f'{len(errors)} files had errors.')
    print(f'File failure rate: {rate} %.')
    if errors and not verbose:
        print('To see which files failed, run with verbose=True.')

    if verbose and errors:
        print('The following files had errors, as run: error_code: '
              f'{ {i: entry.error_code for i, entry in sorted(errors.items())} }')

    return clean, errors


def fix_smalls(dataset, category):
    # CT has an issue where if the scientific notation index is greater than 100 (i.e. 1e-100 or more) then the
    # number does not print properly. Therefore, conversion from string doesn't work. Since outputs can only be
    # numbers, assume any DataArray object that isn't type float64 has values like this, which we can safely assume
    # to be zero.
    for i in dataset:
        if category not in dataset[i].results:
            print(f'{i} does not have category {category}.')
            continue
        else:
            for species in dataset[i].results[category]:
                if dataset[i].results[category][species].dtype == object:
                    dataset[i].results[category][species] = dataset[i].results[category][species].astype(str).str.replace(
                        r'\d.\d+-\d+', '0').astype(float)
                else:
                    continue

    return dataset


def map_smalls(x):
    try:
        x.astype(float)
    except (ValueError, TypeError):
        x = 0

    return x
