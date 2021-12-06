from context import omphalos

if __name__ == '__main__':
    import file_methods as fm
    import generate_inputs as gi
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('path_to_config', type=str, help='YAML file containing options.')
    parser.add_argument('output_name', type=str, help='Output file name.')
    args = parser.parse_args()

    dataset = gi.make_dataset(args.path_to_config)

    # Pickle the data.
    fm.pickle_data_set(dataset, f'{args.output_name}')
