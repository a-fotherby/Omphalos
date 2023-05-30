"""Omphalos analysis helper functions."""


def quick_import(path, smalls_cats=None):
    # Read in data for dict.
    from omphalos import file_methods as fm

    raw = fm.unpickle(path)
    dataset, errors1 = filter_errors(raw)
    #for category in smalls_cats:
    #    dataset = fix_smalls(dataset, category)

    return dataset


def filter_errors(dataset, verbose=False):
    pop_list = list()
    errors = dict()

    for i in dataset:
        if dataset[i].error_code != 0:
            pop_list.append(i)
        else:
            continue

    for j in pop_list:
        errors.update({j: dataset.pop(j)})

    # Check for unidentified errors that are not currently handled.
    # Do this by checking for empty results dict.
    weird_errors = list()
    #for i in dataset:
    #    try:
    #        dataset[i].results['totcon']
    #    except:
    #        weird_errors.append(i)

    for j in weird_errors:
        dataset.pop(j)

    print(f'Returned {len(dataset)} files without errors out of a total possible {len(dataset) + len(errors)}.')
    print(f'{len(errors)} files had errors.')
    print(f'{len(weird_errors)} files had unhandled errors.')
    print(f'File failure rate: {(len(errors) + len(weird_errors)) / len(dataset) * 100} %.')
    print(f'To see unhandled errors, run with verbose=True.')

    if verbose:
        print(f'The following files had unhandled errors: {weird_errors}')

    return dataset, errors


def fix_smalls(dataset, category):
    # CT has an issue where if the scientific notation index is greater than 100 (i.e. 1e-100 or more) then the
    # number does not print properly. Therefore, conversion from string doesn't work. Since outputs can only be
    # numbers, assume any DataArray object that isn't type float64 has values like this, which we can safely assume
    # to be zero.
    for i in dataset:
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
    except:
        x = 0

    return x
