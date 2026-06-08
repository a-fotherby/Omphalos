if __name__ == "__main__":
    import argparse
    import pickle
    import re
    import sys
    from pathlib import Path

    _project_root = Path(__file__).resolve().parent.parent
    if str(_project_root) not in sys.path:
        sys.path.insert(0, str(_project_root))

    import numpy as np
    import xarray as xr
    import yaml

    from omphalos.generate_inputs import CT_IDs, CT_NMLs

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
        config = yaml.safe_load(f)

    # Discover and load completed InputFile pickles from run directories
    directory = Path.cwd()
    run_dirs = sorted(
        [d for d in directory.iterdir() if re.match(r'run\d+$', d.name) and d.is_dir()],
        key=lambda d: int(re.search(r'\d+', d.name).group())
    )

    if not run_dirs:
        print('No run directories found in the current directory.')
        sys.exit(1)

    input_files = {}
    for run_dir in run_dirs:
        run_num = int(re.search(r'\d+', run_dir.name).group())
        pkl_path = run_dir / f'input_file{run_num}_complete.pkl'
        if pkl_path.exists():
            with open(pkl_path, 'rb') as f:
                input_files[run_num] = pickle.load(f)
            print(f'Loaded {pkl_path}')
        else:
            print(f'Warning: {pkl_path} not found, skipping.')

    if not input_files:
        print('No input file pickles found.')
        sys.exit(1)

    file_nums = sorted(input_files.keys())
    output_path = directory / cli_args.output

    if output_path.exists():
        output_path.unlink()

    groups_written = 0

    for block in CT_IDs:
        if block not in config:
            continue

        ct_entry = CT_IDs[block]
        mod_pos = ct_entry[1] if len(ct_entry) > 1 else None

        if isinstance(mod_pos, slice):
            print(f'Skipping block "{block}": slice-type modification not supported.')
            continue

        if block == 'namelists':
            continue

        block_config = config[block]

        if ct_entry[0] == 'geochemical condition':
            for condition, condition_config in block_config.items():
                data_vars = {}
                for entry in condition_config:
                    values = []
                    for fn in file_nums:
                        try:
                            val = input_files[fn].condition_blocks[condition].contents[entry][mod_pos]
                            values.append(float(val))
                        except (KeyError, IndexError, TypeError) as e:
                            print(f'Warning: Could not read {block}/{condition}/{entry} for file {fn}: {e}')
                            values.append(float('nan'))
                    data_vars[entry] = xr.Variable('file_num', np.array(values))

                ds = xr.Dataset(data_vars, coords={'file_num': np.array(file_nums)})
                group = f'{block}/{condition}'
                ds.to_netcdf(output_path, group=group, mode='a')
                print(f'Written group: {group}')
                groups_written += 1

        else:
            block_name = ct_entry[0]
            data_vars = {}
            for entry in block_config:
                values = []
                for fn in file_nums:
                    try:
                        val = input_files[fn].keyword_blocks[block_name].contents[entry][mod_pos]
                        values.append(float(val))
                    except (KeyError, IndexError, TypeError) as e:
                        print(f'Warning: Could not read {block}/{entry} for file {fn}: {e}')
                        values.append(float('nan'))
                data_vars[entry] = xr.Variable('file_num', np.array(values))

            ds = xr.Dataset(data_vars, coords={'file_num': np.array(file_nums)})
            ds.to_netcdf(output_path, group=block, mode='a')
            print(f'Written group: {block}')
            groups_written += 1

    if 'namelists' in config:
        for nml_type, nml_block in config['namelists'].items():
            if nml_type not in CT_NMLs:
                print(f'Warning: Unknown namelist type "{nml_type}", skipping.')
                continue
            nml_attr, list_name = CT_NMLs[nml_type]
            for reaction_name, reaction_config in nml_block.items():
                data_vars = {}
                for parameter in reaction_config:
                    values = []
                    for fn in file_nums:
                        try:
                            namelist = getattr(input_files[fn], nml_attr)
                            reaction = namelist.find_reaction(list_name, reaction_name)
                            values.append(float(reaction[parameter]))
                        except (KeyError, AttributeError, TypeError) as e:
                            print(f'Warning: Could not read namelists/{nml_type}/{reaction_name}/{parameter} for file {fn}: {e}')
                            values.append(float('nan'))
                    data_vars[parameter] = xr.Variable('file_num', np.array(values))

                ds = xr.Dataset(data_vars, coords={'file_num': np.array(file_nums)})
                group = f'namelists/{nml_type}/{reaction_name}'
                ds.to_netcdf(output_path, group=group, mode='a')
                print(f'Written group: {group}')
                groups_written += 1

    if groups_written == 0:
        print('No varied parameters found in the config.')
    else:
        print(f'\nConditions written to {output_path} ({groups_written} group(s))')
