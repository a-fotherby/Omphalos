"""Run Omphalos in parallel using Slurm.

Args:
config -- new option, specifies YAML file containing template modification options. Will replace 'condition' soon.

"""

if __name__ == '__main__':
    import os, sys

    path = os.path.dirname(__file__)
    path = os.path.dirname(path)
    sys.path.insert(0, os.path.abspath(f'{path}'))
    import argparse
    from omphalos.template import Template
    from omphalos import generate_inputs as gi
    import slurm_interface as si
    import subprocess
    import yaml
    from time import time

    parser = argparse.ArgumentParser()
    parser.add_argument('path_to_config', type=str, help='YAML file containing options.')
    args = parser.parse_args()

    # Define procedural file generation name scheme at top for consistency.
    # Do not change as this is not passed to slurm_exec.py
    file_name_scheme = 'input_file'
    dir_name = 'run'

    with open(args.path_to_config) as file:
        config = yaml.full_load(file)

    template = Template(config)
    file_dict = gi.configure_input_files(template, 'foo')

    dict_size = len(file_dict)

    t_start = time()

    subprocess.run([f'parallel "mkdir {dir_name}{{1}}" ::: {{0..{dict_size}}}'], shell=True, executable='/bin/bash')
    subprocess.run([f'parallel "cp {config["database"]} {dir_name}{{1}}/{config["database"]}" ::: {{0..{dict_size}}}'],
                   shell=True, executable='/bin/bash')
    if config['aqueous_database']:
        subprocess.run([
                           f'parallel "cp {config["aqueous_database"]} {dir_name}{{1}}/{config["aqueous_database"]}" ::: {{0..{dict_size}}}'],
                       shell=True, executable='/bin/bash')
    if config['catabolic_pathways']:
        subprocess.run([f'parallel "cp {config["catabolic_pathways"]} {dir_name}{{1}}/{config["catabolic_pathways"]}" ::: '
                        f'{{0..{dict_size}}}'], shell=True, executable='/bin/bash')

    for file in file_dict:
        file_dict[file].path = f'{dir_name}{file}/{file_name_scheme}.in'
        file_dict[file].print()

    t_stop = time()

    print(f'All files generated and directories prepped. Time elapsed: {t_stop - t_start}')

    si.submit(args.path_to_config, config['nodes'], dict_size)
