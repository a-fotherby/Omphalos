
if __name__ == '__main__':
    import sys
    import os
    import file_methods as fm
    import generate_inputs as gi
    import argparse
    import yaml
    from settings import omphalos_path
    sys.path.insert(0, os.path.abspath(f'{omphalos_path}'))
    import run
    from template import Template
    from pathlib import Path
    import shutil

    parser = argparse.ArgumentParser()
    parser.add_argument('config_path', type=str, help='YAML file containing options.')
    parser.add_argument('output_name', type=str, help='Output file name.')
    parser.add_argument('-d', '--debug', action='store_true')
    args = parser.parse_args()

    tmp_dir = 'tmp'
    # Check if tmp_dir exists in the current working directory and create it if not
    if not os.path.exists(tmp_dir):
        os.makedirs(tmp_dir)

    # Import config file.
    with open(args.config_path) as file:
        config = yaml.safe_load(file)

    # Import template file.
    print('*** Importing template file ***')
    template = Template(config)
    # Check if the file exists in the tmp directory
    file_path = os.path.join(tmp_dir, config['database'])
    if os.path.exists(file_path):
        pass
    else:
        shutil.copy(config['database'], tmp_dir)

    # Get a dictionary of input files.
    print('*** Generating input files ***')
    file_dict = gi.configure_input_files(template, tmp_dir)

    if args.debug:
        print("*** DEBUG MODE: FILES NOT RUN ***")
        for file in file_dict:
            file_dict[file].path = f'{file_dict[file].path.parent}/{tmp_dir}/{file}.in'
            file_dict[file].print()
            if file_dict[file].later_inputs:
                print('foo')
                for name in file_dict[file].later_inputs:
                    file_dict[file].later_inputs[name].path = Path(file_dict[file].later_inputs[name].path.parent/tmp_dir/f'{file}_{name}.in')
                    print(file_dict[file].later_inputs[name].path)
                    file_dict[file].later_inputs[name].print()

        sys.exit()
    else:
        print('*** Begin running input files... ***')
        run.run_dataset(file_dict, tmp_dir, config['timeout'])

    # Convert file dict to single xarray for saving as a netCDF4
    print('*** Writing results to results.nc ***')
    ds = fm.dataset_to_netcdf(file_dict)
    ds.to_netcdf('results.nc')
