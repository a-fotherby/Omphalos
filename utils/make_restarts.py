"""Utility script to generate restart input files."""

if __name__ == '__main__':
    import argparse
    import sys
    from pathlib import Path

    # Add parent directory to path for imports
    _project_root = Path(__file__).resolve().parent.parent
    if str(_project_root) not in sys.path:
        sys.path.insert(0, str(_project_root))

    import yaml

    parser = argparse.ArgumentParser()
    parser.add_argument('config', type=str, help='YAML file containing options.')
    parser.add_argument('-p', '--pflotran', action='store_true', default=False, help='Enable Pflotran.')
    args = parser.parse_args()

    if args.pflotran:
        from pflotran.template import Template
        from pflotran import generate_inputs as gi
    else:
        from omphalos.template import Template
        from omphalos import generate_inputs as gi

    # Import config file.
    with open(args.config) as file:
        config = yaml.safe_load(file)

    # Import template file.
    print('*** Importing template file ***')
    template = Template(config)

    print('*** Generating input files ***')
    file_dict = gi.configure_input_files(template, './', rhea=True)

    if args.pflotran:
        for file in file_dict:
            file_dict[file].path = Path.cwd() / file_dict[file].path.name
            file_dict[file].print()
            if file_dict[file].later_inputs:
                for name in file_dict[file].later_inputs:
                    file_dict[file].later_inputs[name].path = Path.cwd() / f'{name}_{file_dict[file].later_inputs[name].path.name}'
                    print(file_dict[file].later_inputs[name].path)
                    file_dict[file].later_inputs[name].print()

    else:
        name_scheme = config['template'].rsplit('.')[0]
        for i, j in enumerate(file_dict):
            file_dict[j].path = f'{name_scheme}_{i+2}.in'
            file_dict[j].keyword_blocks['RUNTIME'].contents['save_restart'] = [f'{name_scheme}_{i+2}.rst']
            if i + 1 == 1:
                file_dict[j].keyword_blocks['RUNTIME'].contents['restart'] = [f'{name_scheme}.rst append']
            else:
                file_dict[j].keyword_blocks['RUNTIME'].contents['restart'] = [f'{name_scheme}_{i+1}.rst append']
                del file_dict[j].keyword_blocks['RUNTIME'].contents['later_inputfiles']

            file_dict[j].print()
