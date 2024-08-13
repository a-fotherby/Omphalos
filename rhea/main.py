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
    parser.add_argument('-d', '--debug', action='store_true')
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
    # Start timer for directory preparation and submission
    t_start = time()

    # Get list of temperature file names
    temperature_files = template.keyword_blocks['TEMPERATURE'].contents['read_temperaturefile']
    if template.later_inputs:
        for file in template.later_inputs:
            temperature_files.append(template.later_inputs[file].keyword_blocks['TEMPERATURE'].contents['read_temperaturefile'][0])

    # Run directory preparation script
    subprocess.run(f'sbatch --array=0-{dict_size} 
                    --export=CONFIG_PATH={args.part_to_config},
                    DATABASE_NAME={config['database']},
                    AQUEOUS_DATABASE={config['aqueous_database']},
                    CATABOLIC_PATHWAYS={config['catabolic_pathways']},
                    TEMPERATURE_FILES={temperature_files},
                    PFLOTRAN={args.pflotran},
                    prep_directories.sh')

    # TODO: DIRECTORIES NEED TO BE MADE BEFORE THIS IS RUN!
    # TODO: FORK DIRECTORY PREPARATION OUT TO A SEPERATE .SH SCRIPT!
    # TODO: Might be able to combine thay with the local directory prep in that case to avoid repeated code.
    # Print files to prepped directories
    for file in file_dict:
        file_dict[file].path = f'{dir_name}{file}/{config["template"]}'
        file_dict[file].print()
        if file_dict[file].later_inputs:
            for later_file in file_dict[file].later_inputs:
                file_dict[file].later_inputs[later_file].path = f'{dir_name}{file}/{file_dict[file].later_inputs[later_file].path}'
                file_dict[file].later_inputs[later_file].print()

    t_stop = time()
    
    print(f'All files generated and directories prepped. Time elapsed: {t_stop - t_start}')
    if args.debug:
        exit('Debug mode: files generated and directories prepped. Exiting before submission.')
    if args.run_type == 'local':
        nodes = config['nodes']
        # Run instances using parallel
        if args.pflotran:
            subprocess.run([f'parallel -P {nodes} python {path}/rhea/slurm_exec.py -p {{}} {args.path_to_config} ::: {{0..{dict_size}}}'], shell=True, executable='/bin/bash')
        else:
            subprocess.run([f'parallel -P {nodes} python {path}/rhea/slurm_exec.py {{}} {args.path_to_config} ::: {{0..{dict_size}}}'], shell=True, executable='/bin/bash')
        # Compile results
        si.compile_results(dict_size+1)
    elif args.run_type == 'cluster':
        subprocess.run(f'sbatch --array=0-{dict_size} 
                        --export=CONFIG_PATH={args.path_to_config},
                        PFLOTRAN={args.pflotran},
                        run_input_file.sh')
    else:
        print('ERROR: run_type must be either local or cluster')