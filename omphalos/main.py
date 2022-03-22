from context import omphalos

if __name__ == '__main__':
    import file_methods as fm
    import generate_inputs as gi
    import argparse
    import yaml
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
    file_dict = gi.configure_input_files(template)

    if args.debug:
        print("*** DEBUG MODE: FILES NOT RUN ***")
    else:
        print('*** Begin running input files... ***')
        run.run_dataset(file_dict, tmp_dir, config['timeout'])

    # Pickle the data.
    print(f"*** Writing data to {args.output_name} ***")
    fm.pickle_data_set(file_dict, f'{args.output_name}')
    print("*** Run complete ***")
