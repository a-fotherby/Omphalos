"""Run Omphalos in parallel using Slurm.

Args:
config -- new option, specifies YAML file containing template modification options.

"""

if __name__ == '__main__':
    import os
    import sys

    path = os.path.dirname(__file__)
    path = os.path.dirname(path)
    sys.path.insert(0, os.path.abspath(f'{path}'))
    import argparse
    import slurm_interface as si
    import subprocess
    import yaml
    from time import time

    parser = argparse.ArgumentParser()
    parser.add_argument('path_to_config', type=str, help='YAML file containing options.')
    parser.add_argument('run_type', type=str, help='Type of run, either local or cluster.')
    parser.add_argument('-p', '--pflotran', action='store_true')
    args = parser.parse_args()

    if args.pflotran:
        from pflotran.template import Template
        from pflotran import generate_inputs as gi
    else:
        from omphalos.template import Template
        from omphalos import generate_inputs as gi

    # Define procedural file generation name scheme at top for consistency.
    # Do not change as this is not passed to slurm_exec.py
    dir_name = 'run'

    with open(args.path_to_config) as file:
        config = yaml.full_load(file)

    template = Template(config)
    file_dict = gi.configure_input_files(template, 'foo', rhea=True)

    dict_size = len(file_dict)-1

    t_start = time()

    print(f'parallel "mkdir {dir_name}{{1}}" ::: {{0..{dict_size}}}')
    subprocess.run([f'parallel "mkdir {dir_name}{{1}}" ::: {{0..{dict_size}}}'], shell=True, executable='/bin/bash')
    subprocess.run([f'parallel "cp {config["database"]} {dir_name}{{1}}/{config["database"]}" ::: {{0..{dict_size}}}'],
                   shell=True, executable='/bin/bash')
    if args.pflotran:
        pass
    else:
        if config['aqueous_database'] is not None:
            subprocess.run([
                f'parallel "cp {config["aqueous_database"]} {dir_name}{{1}}/{config["aqueous_database"]}" ::: {{0..{dict_size}}}'],
                shell=True, executable='/bin/bash')
        if config['catabolic_pathways'] is not None:
            subprocess.run([f'parallel "cp {config["catabolic_pathways"]} {dir_name}{{1}}/{config["catabolic_pathways"]}" ::: '
                            f'{{0..{dict_size}}}'], shell=True, executable='/bin/bash')
        try:
            if template.keyword_blocks['TEMPERATURE'].contents['read_temperaturefile']:
                t_file = template.keyword_blocks['TEMPERATURE'].contents['read_temperaturefile'][0]
                subprocess.run([f'parallel "cp {t_file} {dir_name}{{1}}/{t_file}" ::: '
                                f'{{0..{dict_size}}}'], shell=True, executable='/bin/bash')
                if template.later_inputs:
                    for file in template.later_inputs:
                        t_file = template.later_inputs[file].keyword_blocks['TEMPERATURE'].contents['read_temperaturefile'][0]
                        subprocess.run([f'parallel "cp {t_file} {dir_name}{{1}}/{t_file}" ::: '
                                        f'{{0..{dict_size}}}'], shell=True, executable='/bin/bash')
        except KeyError:
            pass

    for file in file_dict:
        file_dict[file].path = f'{dir_name}{file}/{config["template"]}'
        file_dict[file].print()
        if file_dict[file].later_inputs:
            for later_file in file_dict[file].later_inputs:
                file_dict[file].later_inputs[later_file].path = f'{dir_name}{file}/{file_dict[file].later_inputs[later_file].path}'
                file_dict[file].later_inputs[later_file].print()

    t_stop = time()
    
    print(f'All files generated and directories prepped. Time elapsed: {t_stop - t_start}')
    if args.run_type == 'local':
        nodes = config['nodes']
        if args.pflotran:
            subprocess.run([f'parallel -P {nodes} python {path}/rhea/slurm_exec.py -p {{}} {args.path_to_config} ::: {{0..{dict_size}}}'], shell=True, executable='/bin/bash')
        else:
            subprocess.run([f'parallel -P {nodes} python {path}/rhea/slurm_exec.py {{}} {args.path_to_config} ::: {{0..{dict_size}}}'], shell=True, executable='/bin/bash')

        si.compile_results(dict_size+1)
    elif args.run_type == 'cluster':
        si.submit(args.path_to_config, config['nodes'], dict_size)
    else:
        print('ERROR: run_type must be either local or cluster')