if __name__ == '__main__':
    import argparse
    import context
    import yaml
    from omphalos.template import Template
    from omphalos import generate_inputs as gi

    parser = argparse.ArgumentParser()
    parser.add_argument('config', type=str, help='YAML file containing options.')
    args = parser.parse_args()

    # Import config file.
    with open(args.config) as file:
        config = yaml.safe_load(file)

    # Import template file.
    print('*** Importing template file ***')
    template = Template(config)

    print('*** Generating input files ***')
    file_dict = gi.configure_input_files(template, './', rhea=True)

    name_scheme = config['template'].rsplit('.')[0]
    for i,j in enumerate(file_dict):
        file_dict[j].path = f'{name_scheme}{i+2}.in'
        file_dict[j].keyword_blocks['RUNTIME'].contents['save_restart'] = [file_dict[j].path]
        if i+1 == 1:
            file_dict[j].keyword_blocks['RUNTIME'].contents['restart'] = [f'{name_scheme}.in']
        else:
            file_dict[j].keyword_blocks['RUNTIME'].contents['restart'] = [f'{name_scheme}{i+1}.in']

        file_dict[j].print()
