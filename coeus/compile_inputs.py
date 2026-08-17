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
    """Return a name netCDF can hold.

    Group and variable names may not contain '/', which netCDF reads as a path separator. Database
    entry names are chemical formulae and rate law labels, so most punctuation is fine and only the
    slash needs replacing.
    """
    return str(name).replace('/', '_')


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


def compile_inputs(config, output='conditions.nc', directory=None, verbose=True):
    """Write the parameter values a sweep actually used to a netCDF file.

    Values are read from the per-run pickles, so they reflect what ran rather than what the config
    asked for. Parameters using the 'staged' method are re-derived from the config for each stage,
    since a single input file only carries the values of its own stage.

    Args:
        config: The run's config, as a dict.
        output: Output file name, written inside directory.
        directory: Directory holding the run directories (default: the current directory).
        verbose: Whether to name each pickle and group as it is handled.

    Returns:
        dict: 'output' (Path written, or None if nothing was), 'groups' (number written), 'runs'
        (run numbers read) and 'missing' (run numbers whose pickle was absent).

    Raises:
        FileNotFoundError: If there are no run directories, or none of them holds a pickle.
    """
    import numpy as np
    import xarray as xr

    from omphalos.generate_inputs import CT_IDs, CT_NMLs, evaluate_config

    directory = Path(directory) if directory is not None else Path.cwd()

    # Auto-detect staged runs from the config
    staged_mode = bool(config.get('restart_chain') and config['restart_chain'].get('stages'))
    num_stages = config['restart_chain']['stages'] if staged_mode else 0
    stage_configs = {}
    stage_nums = None
    if staged_mode:
        print(f'Staged run detected ({num_stages} stages). Re-deriving staged parameter values from config.')
        stage_configs = {s: evaluate_config(config, stage_num=s) for s in range(num_stages)}
        stage_nums = np.arange(num_stages)

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
                        values = []
                        for fn in file_nums:
                            try:
                                val = input_files[fn].condition_blocks[condition].contents[entry][mod_pos]
                                values.append(float(val))
                            except (KeyError, IndexError, TypeError) as e:
                                print(f'Warning: Could not read {block}/{condition}/{entry} for file {fn}: {e}')
                                values.append(float('nan'))
                        data_vars[entry] = make_var(values)

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
                    values = []
                    for fn in file_nums:
                        try:
                            val = input_files[fn].keyword_blocks[block_name].contents[entry][mod_pos]
                            values.append(float(val))
                        except (KeyError, IndexError, TypeError) as e:
                            print(f'Warning: Could not read {block}/{entry} for file {fn}: {e}')
                            values.append(float('nan'))
                    data_vars[entry] = make_var(values)

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
            for setting in swept:
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
    cli_args = parser.parse_args()

    with open(cli_args.config) as f:
        run_config = yaml.safe_load(f)

    warning = pairing_warning(output=cli_args.output)
    if warning:
        print(warning)

    try:
        compile_inputs(run_config, output=cli_args.output)
    except FileNotFoundError as error:
        sys.exit(str(error))
