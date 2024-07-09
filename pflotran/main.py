
if __name__ == '__main__':
    import sys
    import os
    import file_methods as fm
    import generate_inputs as gi
    import argparse
    import yaml
    from settings import omphalos_path
    sys.path.insert(0, os.path.abspath(f'{omphalos_path}'))
    import omphalos.run as run
    from omphalos.template import Template

    parser = argparse.ArgumentParser()
    parser.add_argument('config_path', type=str, help='YAML file containing options.')
    parser.add_argument('output_name', type=str, help='Output file name.')
    parser.add_argument('-d', '--debug', action='store_true')
    args = parser.parse_args()

    tmp_dir = 'tmp/'

    # Import config file.
    with open(args.config_path) as file:
        config = yaml.safe_load(file)

    # Import template file.
    print('*** Importing template file ***')
    template = Template(config)
    # Get a dictionary of input files.
    print('*** Generating input files ***')
    file_dict = gi.configure_input_files(template, tmp_dir)

    if args.debug:
        print("*** DEBUG MODE: FILES NOT RUN ***")
        for file in file_dict:
            file_dict[file].path = f'{tmp_dir}{file_dict[file].path}{file}'
            file_dict[file].print()

        sys.exit()
    else:
        print('*** Begin running input files... ***')
        run.run_dataset(file_dict, tmp_dir, config['timeout'])

    # Convert file dict to single xarray for saving as a netCDF4
    print('*** Writing results to results.nc ***')
    fm.dataset_to_netcdf(file_dict)

    # Delete data from the InputFile object.
    # I know this seems a little round-about, but either way when collecting the data the data needs to be assembled
    # into the per-file data for each category, and then concatenated along the file number axis.
    # Whether this is done in the InputFile object itself or some other dict is neither here nor there and there is
    # little point in rewriting the code just to elide that one slightly inelegant detail.

    for file in file_dict:
        del file_dict[file].results

    # Pickle the data.
    print(f"*** Writing InputFile record to {args.output_name} ***")
    fm.pickle_data_set(file_dict, f'{args.output_name}')
    print("*** Run complete ***")
