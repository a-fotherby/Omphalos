"""Main entry point for running Omphalos (CrunchTope) simulations."""

if __name__ == '__main__':
    import argparse
    import sys
    from pathlib import Path

    # Add parent directory to path for imports
    _project_root = Path(__file__).resolve().parent.parent
    if str(_project_root) not in sys.path:
        sys.path.insert(0, str(_project_root))

    import yaml
    from omphalos import file_methods as fm
    from omphalos import generate_inputs as gi
    from omphalos import run
    from omphalos.template import Template

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

    # Check once, before any run, that the deck spells its auxiliary-database keywords the way this
    # CrunchTope build reads them. A mismatch is silent at run time: CrunchTope ignores the keyword
    # and carries on without the database.
    import omphalos.crunch_keywords as ck
    ck.check_deck(template.keyword_blocks['RUNTIME'].contents)

    # Get a dictionary of input files.
    print('*** Generating input files ***')
    file_dict = gi.configure_input_files(template, str(tmp_dir) + '/')

    if args.debug:
        print("*** DEBUG MODE: FILES NOT RUN ***")
        # Number the files before the extension, and take only the template's file name: appending the
        # run number to the path as given produced names like 'column.in0', and wrote next to the
        # template rather than into tmp/ when the template was an absolute path.
        template_path = Path(config['template'])
        for file in file_dict:
            file_dict[file].path = tmp_dir / f'{template_path.stem}{file}{template_path.suffix}'
            file_dict[file].print()
            print(f'Wrote {file_dict[file].path}')

        sys.exit()
    else:
        print('*** Begin running input files... ***')
        run.run_dataset(file_dict, str(tmp_dir) + '/', config['timeout'])

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
    fm.pickle_data_set(file_dict, args.output_name)
    print("*** Run complete ***")
