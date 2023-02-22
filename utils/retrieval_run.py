def maxtime(dir):
    import os
    from glob import glob
    os.chdir(dir)
    f_list = glob('*.tec')
    f_list = [i.rstrip('.tec') for i in f_list]
    f_list = [i.rstrip('0123456789') for i in f_list]
    f_set = set(f_list)
    max_time = int(len(f_list) / len(f_set))
    os.chdir('..')
    return max_time


if __name__ == "__main__":
    import argparse
    import context
    import yaml
    from omphalos.template import Template
    from omphalos.input_file import InputFile
    from omphalos import generate_inputs as gi
    from omphalos import file_methods as fm
    import numpy as np

    parser = argparse.ArgumentParser()
    parser.add_argument('path', type=str, help='File path.')
    parser.add_argument('num_files', type=int, help='Number of run to attempt to retrieve.')
    args = parser.parse_args()

    mini_conf = {'template': args.path, 'number_of_files': args.num_files, 'aqueous_database': None,
                 'catabolic_pathways': None}

    template = Template(mini_conf)

    file_dict = template.make_dict()

    for file in file_dict:
        # Calculate number of timesteps that were recorded in each InputFile
        # Overwrite self.keyword_blocks['OUTPUT'].contents['spatial_profile'] for each file
        # Create correct tmp_dir
        # Call InputFile.get_results(tmp_dir)

        dir = f'run{file}'
        print(dir)
        final_time = maxtime(dir)
        file_dict[file].get_results(dir)

    fm.pickle_data_set(file_dict, 'retrieval_run.pkl')
