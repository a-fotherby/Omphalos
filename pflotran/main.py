"""Main entry point for running PFLOTRAN simulations."""

if __name__ == '__main__':
    import argparse
    import shutil
    import sys
    from pathlib import Path

    # Add parent directory to path for imports
    _project_root = Path(__file__).resolve().parent.parent
    if str(_project_root) not in sys.path:
        sys.path.insert(0, str(_project_root))

    import yaml
    from pflotran import file_methods as fm
    from pflotran import generate_inputs as gi
    from pflotran import run
    from pflotran.template import Template

    parser = argparse.ArgumentParser()
    parser.add_argument('config_path', type=str, help='YAML file containing options.')
    parser.add_argument('output_name', type=str, help='Output file name.')
    parser.add_argument('-d', '--debug', action='store_true')
    args = parser.parse_args()

    tmp_dir = Path('tmp')
    tmp_dir.mkdir(exist_ok=True)

    # Import config file.
    with open(args.config_path) as file:
        config = yaml.safe_load(file)

    # Import template file.
    print('*** Importing template file ***')
    template = Template(config)

    # Check if the database file exists in the tmp directory
    file_path = tmp_dir / config['database']
    if not file_path.exists():
        shutil.copy(config['database'], tmp_dir)

    # Get a dictionary of input files.
    print('*** Generating input files ***')
    file_dict = gi.configure_input_files(template, str(tmp_dir))

    if args.debug:
        print("*** DEBUG MODE: FILES NOT RUN ***")
        for file in file_dict:
            file_dict[file].path = file_dict[file].path.parent / tmp_dir / f'{file}.in'
            file_dict[file].print()
            if file_dict[file].later_inputs:
                for name in file_dict[file].later_inputs:
                    file_dict[file].later_inputs[name].path = file_dict[file].later_inputs[name].path.parent / tmp_dir / f'{file}_{name}.in'
                    print(file_dict[file].later_inputs[name].path)
                    file_dict[file].later_inputs[name].print()

        sys.exit()
    else:
        print('*** Begin running input files... ***')
        run.run_dataset(file_dict, str(tmp_dir), config['timeout'])

    # Convert file dict to single xarray for saving as a netCDF4
    print('*** Writing results to results.nc ***')
    ds = fm.dataset_to_netcdf(file_dict, simulator='pflotran')
    ds.to_netcdf('results.nc')
