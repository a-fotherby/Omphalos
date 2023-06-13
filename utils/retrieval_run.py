"""Script to recover data from failed rhea runs.
Will return pickled file dict as usual, with as many timesteps as it can find in each directory.
"""

if __name__ == "__main__":
    import argparse
    import context
    import yaml
    from omphalos.template import Template
    from omphalos.input_file import InputFile
    from omphalos import generate_inputs as gi
    from omphalos import file_methods as fm
    import numpy as np
    import pathlib as pl

    parser = argparse.ArgumentParser()
    parser.add_argument('path', type=str, help='File path.')
    parser.add_argument('num_files', type=int, help='Number of run to attempt to retrieve.')
    parser.add_argument('-s', '--single', action='store_true', help='Recover a single CrunchTope run. Will search for '
                                                                    'output files in the same directory as path, '
                                                                    'rather than in the rhea folder structure.')
    args = parser.parse_args()

    if args.single:
        args.num_files = 1

    mini_conf = {'template': args.path, 'number_of_files': args.num_files, 'aqueous_database': None,
                 'catabolic_pathways': None}

    template = Template(mini_conf)

    file_dict = template.make_dict()

    if args.single:
        for file in file_dict:
            print(pl.Path(args.path).parent.resolve())
            file_dict[file].get_results(pl.Path(args.path).parent.resolve())
    else:
        for file in file_dict:
            # Calculate number of timesteps that were recorded in each InputFile
            # Overwrite self.keyword_blocks['OUTPUT'].contents['spatial_profile'] for each file
            # Create correct tmp_dir
            # Call InputFile.get_results(tmp_dir)
            print(f'Retrieving file #{file}')

            dir = f'run{file}'
            file_dict[file].get_results(dir)

    fm.dataset_to_netcdf(file_dict)
    fm.pickle_data_set(file_dict, 'retrieval_run.pkl')
