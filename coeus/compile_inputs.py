"""Compile the varied input parameters of a rhea run into a netCDF file.

Run as a script after a sweep, or called by ``rhea <config> local --compile-inputs`` to have it happen
as part of the run. Reads the completed ``input_file<N>_complete.pkl`` written into each ``run<N>/``
directory and records the parameter values those runs actually used, in groups mirroring the config.

Essential for ``random_uniform`` sweeps, where the YAML alone cannot say what was run.
"""

import pickle
import re
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


def _netcdf_name(name):
    """Return a name netCDF can hold, by the same rule the results file uses.

    Database entry names are chemical formulae and rate law labels, so most punctuation is fine: it
    is the '/' anywhere, and a first character that is neither alphanumeric nor an underscore, that
    netCDF refuses. A surface complex is named '>FeOHZn+_w' and hits the second -- and because
    `rhea` treats a failed record as a warning beside results it has already written, the whole
    record went missing with only a line of output to say so.
    """
    from core.file_methods import netcdf_name

    return netcdf_name(name)


def _values_from_tokens(tokens, make_var):
    """Wrap per-run tokens into an xr.Variable, as numbers where they are numbers.

    A swept value is usually a number, but not always: the ISOTOPES block's recrystallisation option
    is `bulk`, `surface` or `none`, and a condition entry may read `charge`. Those have no numeric
    value to record and would be lost entirely as a column of NaNs -- and `float('bulk')` raises
    ValueError, which used to escape uncaught and take the whole record with it.

    Args:
        tokens: One raw token per run, or None where the run could not be read.
        make_var: Wraps a list of per-run values into an xr.Variable.

    Returns:
        An xr.Variable of floats, or of strings where any readable token is not a number.
    """
    numbers = []

    for raw in tokens:
        if raw is None:
            numbers.append(None)
            continue
        try:
            numbers.append(float(raw))
        except (TypeError, ValueError):
            numbers.append(None)

    readable = [number for raw, number in zip(tokens, numbers) if raw is not None]

    # Vacuously true where nothing could be read, which is a column of NaNs: nothing there says the
    # sweep was of anything but numbers.
    if all(number is not None for number in readable):
        return make_var([float('nan') if number is None else number for number in numbers])

    return make_var(['' if raw is None else str(raw) for raw in tokens])


def _min3p_token(input_file, block_name, keyword, line, token):
    """Return the raw token at a MIN3P modification's coordinate.

    Resolved with generate_inputs' own helpers rather than a second lookup written here, so the
    coordinate a sweep was applied at and the coordinate it is read back from cannot drift apart.
    """
    from min3p.generate_inputs import _resolve_block

    return _resolve_block(input_file, block_name).contents[keyword][line].tokens[token]


def _min3p_number(token):
    """Return a MIN3P token as a float, or None where it is not one.

    MIN3P writes Fortran double-precision exponents ('1.00d-2'), which float() rejects, and a
    modification may legitimately set an enumerated string ("'geometric'"), which is not a number at
    all.
    """
    text = str(token).strip().strip("'")

    try:
        return float(text.replace('d', 'e').replace('D', 'E'))
    except ValueError:
        return None


def load_input_files(directory, verbose=True):
    """Load the completed InputFile pickle from every run directory under directory.

    Args:
        directory: Directory holding the run0/, run1/, ... directories.
        verbose: Whether to name each pickle as it is loaded.

    Returns:
        (input_files, missing): a dict of {run number: InputFile}, and the run numbers whose pickle
        was absent (a run that failed before it could record anything).

    Raises:
        FileNotFoundError: If there are no run directories, or none of them holds a pickle.
    """
    directory = Path(directory)
    run_dirs = sorted(
        [d for d in directory.iterdir() if re.match(r'run\d+$', d.name) and d.is_dir()],
        key=lambda d: int(re.search(r'\d+', d.name).group())
    )

    if not run_dirs:
        raise FileNotFoundError(f'No run directories found in {directory}.')

    input_files = {}
    missing = []
    for run_dir in run_dirs:
        run_num = int(re.search(r'\d+', run_dir.name).group())
        pkl_path = run_dir / f'input_file{run_num}_complete.pkl'
        if pkl_path.exists():
            with open(pkl_path, 'rb') as f:
                input_files[run_num] = pickle.load(f)
            if verbose:
                print(f'Loaded {pkl_path}')
        else:
            missing.append(run_num)
            print(f'Warning: {pkl_path} not found, skipping.')

    if not input_files:
        raise FileNotFoundError(f'No input file pickles found in {directory}.')

    return input_files, missing


def pairing_warning(directory='.', output='conditions.nc'):
    """Return a warning if the chosen name may not pair with the results file intended, else None.

    results.nc is numbered when a sweep is re-run in the same directory — results1.nc, results2.nc —
    and each parameter record belongs to the results file carrying the same suffix. Writing the
    default conditions.nc where several results files exist therefore pairs it with the *first* sweep,
    which may not be the one meant; both are indexed by run number, so a mismatch would join
    silently. `rhea --compile-inputs` derives the name from the results it just wrote and cannot hit
    this.
    """
    from core.file_methods import matching_output_name

    if output != 'conditions.nc':
        return None

    results = sorted(p.name for p in Path(directory).glob('results*.nc'))
    if len(results) < 2:
        return None

    suggestions = ', '.join(f'{r} -> {matching_output_name(r)}' for r in results)
    return (f'Warning: {len(results)} results files here ({", ".join(results)}). This record is being '
            f'written to conditions.nc, which pairs with results.nc. For another sweep, pass -o to '
            f'match it: {suggestions}.')


def _write_min3p_record(config, input_files, file_nums, make_var, make_coords, write, xr):
    """Write the 'modifications' group of a MIN3P sweep, and return the number of groups written.

    A MIN3P parameter is a token at a positional coordinate rather than a named entry, so there is
    nothing to group by: every modification the config names becomes one variable of a single
    'modifications' group, under the name the config gave it.

    Args:
        config: The run's config, as a dict.
        input_files: {run number: InputFile}, as loaded from the per-run pickles.
        file_nums: The run numbers, in order.
        make_var: Wraps a list of per-run values into an xr.Variable.
        make_coords: Returns the coordinates those variables are indexed by.
        write: Writes a dataset into a named group.
        xr: The xarray module (imported by the caller, which is where the dependency belongs).

    Returns:
        1 if a group was written, 0 if the config varies nothing.
    """
    from min3p.generate_inputs import _coordinates

    data_vars = {}

    for name, spec in (config.get('modifications') or {}).items():
        block_name, keyword, line, token = _coordinates(spec)
        tokens = []

        for file_num in file_nums:
            try:
                tokens.append(_min3p_token(input_files[file_num], block_name, keyword, line, token))
            except (KeyError, IndexError, AttributeError, TypeError) as error:
                print(f'Warning: Could not read modifications/{name} for file {file_num}: {error}')
                tokens.append(None)

        numbers = [None if raw is None else _min3p_number(raw) for raw in tokens]
        readable = [number for raw, number in zip(tokens, numbers) if raw is not None]

        # Vacuously true where no run could be read at all, which is a column of NaNs rather than a
        # column of empty strings: nothing there says the sweep was of anything but numbers.
        if all(number is not None for number in readable):
            # An unreadable coordinate becomes NaN, as it does for every CrunchTope block.
            data_vars[_netcdf_name(name)] = make_var(
                [float('nan') if number is None else number for number in numbers]
            )
        else:
            # A modification may set an enumerated string ("'geometric'"), which has no numeric
            # value to record and would be lost entirely as a column of NaNs.
            data_vars[_netcdf_name(name)] = make_var(
                ['' if raw is None else str(raw).strip("'") for raw in tokens]
            )

    if not data_vars:
        return 0

    write(xr.Dataset(data_vars, coords=make_coords()), 'modifications')

    return 1


def compile_inputs(config, output='conditions.nc', directory=None, verbose=True,
                   simulator='crunchtope'):
    """Write the parameter values a sweep actually used to a netCDF file.

    Values are read from the per-run pickles, so they reflect what ran rather than what the config
    asked for. Parameters using the 'staged' method are re-derived from the config for each stage,
    since a single input file only carries the values of its own stage.

    The two backends describe their parameters differently and so are recorded differently. A
    CrunchTope config names keyword blocks and conditions, and each becomes a netCDF group. A MIN3P
    config instead names positional coordinates under 'modifications', and those become one group of
    that name, with a variable per modification.

    Args:
        config: The run's config, as a dict.
        output: Output file name, written inside directory.
        directory: Directory holding the run directories (default: the current directory).
        verbose: Whether to name each pickle and group as it is handled.
        simulator: 'crunchtope' (default) or 'min3p', matching the backend the sweep ran on.

    Returns:
        dict: 'output' (Path written, or None if nothing was), 'groups' (number written), 'runs'
        (run numbers read) and 'missing' (run numbers whose pickle was absent).

    Raises:
        FileNotFoundError: If there are no run directories, or none of them holds a pickle.
        ValueError: If simulator names a backend this cannot record.
    """
    import numpy as np
    import xarray as xr

    simulator = (simulator or 'crunchtope').lower()

    if simulator not in ('crunchtope', 'min3p'):
        raise ValueError(
            f"Cannot record a '{simulator}' sweep. Supported backends: 'crunchtope', 'min3p'."
        )

    directory = Path(directory) if directory is not None else Path.cwd()

    # Auto-detect staged runs from the config
    staged_mode = bool(config.get('restart_chain') and config['restart_chain'].get('stages'))
    num_stages = config['restart_chain']['stages'] if staged_mode else 0
    stage_configs = {}
    stage_nums = None
    if staged_mode:
        stage_nums = np.arange(num_stages)

        if simulator == 'crunchtope':
            from omphalos.generate_inputs import evaluate_config

            print(f'Staged run detected ({num_stages} stages). Re-deriving staged parameter values from config.')
            stage_configs = {s: evaluate_config(config, stage_num=s) for s in range(num_stages)}
        else:
            # A MIN3P chain applies the same modifications to every stage and varies only the final
            # solution time, which the config states outright and no run has to be read for. The
            # values below are therefore the same across stages, and carry the dimension only so
            # they align with a staged results file.
            print(f'Staged run detected ({num_stages} stages). MIN3P varies only the final solution '
                  f'time by stage; the modification values are those every stage used.')

    input_files, missing = load_input_files(directory, verbose=verbose)
    file_nums = sorted(input_files.keys())
    output_path = directory / output

    if output_path.exists():
        output_path.unlink()

    def make_var(values_1d):
        """Wrap per-file values into an xr.Variable, tiling across stages if in staged mode."""
        arr = np.array(values_1d)
        if staged_mode:
            return xr.Variable(['file_num', 'stage_num'], np.tile(arr[:, np.newaxis], (1, num_stages)))
        return xr.Variable('file_num', arr)

    def staged_var(stage_arrays):
        """Build an xr.Variable from per-stage arrays for parameters using the staged method."""
        arr = np.array([[float(stage_arrays[s][fn]) for s in range(num_stages)] for fn in file_nums])
        return xr.Variable(['file_num', 'stage_num'], arr)

    def database_var(values):
        """Wrap per-file database values, which may be a vector over the temperature points.

        A mineral or secondary species log K is one value per temperature point, so it gains a
        temp_point dimension; an exchange coefficient or a rate constant is a single number and does
        not.
        """
        if not any(isinstance(value, list) for value in values):
            return make_var([float(value) for value in values])

        width = max(len(value) if isinstance(value, list) else 1 for value in values)
        array = np.array(
            [value if isinstance(value, list) else [value] * width for value in values],
            dtype=float,
        )

        if staged_mode:
            return xr.Variable(['file_num', 'stage_num', 'temp_point'],
                               np.tile(array[:, np.newaxis, :], (1, num_stages, 1)))

        return xr.Variable(['file_num', 'temp_point'], array)

    def make_coords():
        coords = {'file_num': np.array(file_nums)}
        if staged_mode:
            coords['stage_num'] = stage_nums
        return coords

    def write(dataset, group):
        dataset.to_netcdf(output_path, group=group, mode='a')
        if verbose:
            print(f'Written group: {group}')

    groups_written = 0

    if simulator == 'min3p':
        groups_written += _write_min3p_record(config, input_files, file_nums, make_var, make_coords,
                                              write, xr)

        if groups_written == 0:
            print('No varied parameters found in the config.')
            return {'output': None, 'groups': 0, 'runs': file_nums, 'missing': missing}

        print(f'\nConditions written to {output_path} ({groups_written} group(s))')
        return {'output': output_path, 'groups': groups_written, 'runs': file_nums,
                'missing': missing}

    from omphalos.generate_inputs import CT_IDs, CT_NMLs

    for block in CT_IDs:
        if block not in config:
            continue

        ct_entry = CT_IDs[block]
        mod_pos = ct_entry[1] if len(ct_entry) > 1 else None

        if isinstance(mod_pos, slice):
            print(f'Skipping block "{block}": slice-type modification not supported.')
            continue

        # All three are shaped differently from a keyword block and are handled after this loop.
        if block in ('namelists', 'database_parameters', 'database_logk'):
            continue

        block_config = config[block]

        if ct_entry[0] == 'geochemical condition':
            for condition, condition_config in block_config.items():
                data_vars = {}
                for entry, entry_spec in condition_config.items():
                    if staged_mode and entry_spec[0] == 'staged':
                        data_vars[entry] = staged_var(
                            {s: stage_configs[s][block][condition][entry] for s in range(num_stages)}
                        )
                    else:
                        tokens = []
                        for fn in file_nums:
                            try:
                                tokens.append(
                                    input_files[fn].condition_blocks[condition].contents[entry][mod_pos])
                            except (KeyError, IndexError, TypeError) as e:
                                print(f'Warning: Could not read {block}/{condition}/{entry} for file {fn}: {e}')
                                tokens.append(None)
                        data_vars[entry] = _values_from_tokens(tokens, make_var)

                write(xr.Dataset(data_vars, coords=make_coords()), f'{block}/{condition}')
                groups_written += 1

        else:
            block_name = ct_entry[0]
            data_vars = {}
            for entry, entry_spec in block_config.items():
                if staged_mode and entry_spec[0] == 'staged':
                    data_vars[entry] = staged_var(
                        {s: stage_configs[s][block][entry] for s in range(num_stages)}
                    )
                else:
                    tokens = []
                    for fn in file_nums:
                        try:
                            tokens.append(
                                input_files[fn].keyword_blocks[block_name].contents[entry][mod_pos])
                        except (KeyError, IndexError, TypeError) as e:
                            print(f'Warning: Could not read {block}/{entry} for file {fn}: {e}')
                            tokens.append(None)
                    data_vars[_netcdf_name(entry)] = _values_from_tokens(tokens, make_var)

            write(xr.Dataset(data_vars, coords=make_coords()), block)
            groups_written += 1

    if 'namelists' in config:
        for nml_type, nml_block in config['namelists'].items():
            if nml_type not in CT_NMLs:
                print(f'Warning: Unknown namelist type "{nml_type}", skipping.')
                continue
            nml_attr, list_name = CT_NMLs[nml_type]
            for reaction_name, reaction_config in nml_block.items():
                data_vars = {}
                for parameter, param_spec in reaction_config.items():
                    if staged_mode and param_spec[0] == 'staged':
                        data_vars[parameter] = staged_var(
                            {s: stage_configs[s]['namelists'][nml_type][reaction_name][parameter]
                             for s in range(num_stages)}
                        )
                    else:
                        values = []
                        for fn in file_nums:
                            try:
                                namelist = getattr(input_files[fn], nml_attr)
                                reaction = namelist.find_reaction(list_name, reaction_name)
                                values.append(float(reaction[parameter]))
                            except (KeyError, AttributeError, TypeError) as e:
                                print(f'Warning: Could not read namelists/{nml_type}/{reaction_name}/{parameter} for file {fn}: {e}')
                                values.append(float('nan'))
                        data_vars[parameter] = make_var(values)

                write(xr.Dataset(data_vars, coords=make_coords()), f'namelists/{nml_type}/{reaction_name}')
                groups_written += 1

    if 'database_parameters' in config:
        for section, section_config in config['database_parameters'].items():
            for entry, entry_config in section_config.items():
                data_vars = {}
                for parameter, param_spec in entry_config.items():
                    if staged_mode and param_spec[0] == 'staged':
                        data_vars[_netcdf_name(parameter)] = staged_var(
                            {s: stage_configs[s]['database_parameters'][section][entry][parameter]
                             for s in range(num_stages)}
                        )
                    else:
                        values = []
                        for fn in file_nums:
                            try:
                                values.append(input_files[fn].database.value(section, entry,
                                                                             parameter))
                            except (AttributeError, KeyError, TypeError) as e:
                                print(f'Warning: Could not read database_parameters/{section}/'
                                      f'{entry}/{parameter} for file {fn}: {e}')
                                values.append(float('nan'))
                        data_vars[_netcdf_name(parameter)] = database_var(values)

                write(xr.Dataset(data_vars, coords=make_coords()),
                      f'database_parameters/{section}/{_netcdf_name(entry)}')
                groups_written += 1

    if 'database_logk' in config:
        from omphalos.generate_inputs import split_logk_settings

        _, swept = split_logk_settings(config['database_logk'])

        if swept:
            # Every other block here is read back from what ran. This one cannot be: a CrunchTope
            # database has no pressure row, so a database recomputed at 500 bar is byte-comparable
            # to one at saturation and says nothing about which it is. The settings each run was
            # recomputed with are therefore recorded on the InputFile at generation time, and read
            # from the pickle here -- which is still what ran, not what the config asked for.
            data_vars = {}
            for setting, spec in swept.items():
                if staged_mode and spec[0] == 'staged':
                    # One pickle survives per run, so it can only carry one stage's settings --
                    # reading it would record that stage's value for every stage. Re-derived from
                    # the config instead, exactly as the other blocks do for a staged sweep.
                    data_vars[_netcdf_name(setting)] = staged_var(
                        {s: stage_configs[s]['database_logk']['swept'][setting]
                         for s in range(num_stages)}
                    )
                    continue

                values = []
                for fn in file_nums:
                    used = getattr(input_files[fn], 'logk_settings', None) or {}
                    if setting not in used:
                        print(f'Warning: Could not read database_logk/{setting} for file {fn}: '
                              f'the run records no recomputation settings.')
                        values.append(float('nan'))
                    else:
                        values.append(used[setting])
                data_vars[_netcdf_name(setting)] = database_var(values)

            write(xr.Dataset(data_vars, coords=make_coords()), 'database_logk')
            groups_written += 1

    if groups_written == 0:
        print('No varied parameters found in the config.')

        if config.get('modifications'):
            # The one shape of config that reaches here with nothing recorded and plenty varied.
            print("This config varies 'modifications', which is how a MIN3P sweep is written. "
                  'Pass -m to record it.')

        return {'output': None, 'groups': 0, 'runs': file_nums, 'missing': missing}

    print(f'\nConditions written to {output_path} ({groups_written} group(s))')
    return {'output': output_path, 'groups': groups_written, 'runs': file_nums, 'missing': missing}


if __name__ == "__main__":
    import argparse

    import yaml

    parser = argparse.ArgumentParser(
        description='Compile varied input conditions from a rhea run into a netCDF file.'
    )
    parser.add_argument('config', help='Path to the YAML config file used for the run')
    parser.add_argument(
        '-o', '--output', default='conditions.nc',
        help='Output filename (default: conditions.nc)'
    )
    parser.add_argument(
        '-m', '--min3p', action='store_true',
        help="Read the run as a MIN3P sweep, recording its 'modifications' rather than CrunchTope "
             'config blocks'
    )
    cli_args = parser.parse_args()

    with open(cli_args.config) as f:
        run_config = yaml.safe_load(f)

    warning = pairing_warning(output=cli_args.output)
    if warning:
        print(warning)

    try:
        compile_inputs(run_config, output=cli_args.output,
                       simulator='min3p' if cli_args.min3p else 'crunchtope')
    except FileNotFoundError as error:
        sys.exit(str(error))
