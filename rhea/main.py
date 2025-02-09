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
    import time

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
    t_start = time.time()

    # Get list of temperature file names
    temperature_files = []
    try: 
        temperature_files = template.keyword_blocks['TEMPERATURE'].contents['read_temperaturefile']
        print(f'Temperature file found:{temperature_files}') 
        if template.later_inputs:
            for file in template.later_inputs:
                temperature_files.append(template.later_inputs[file].keyword_blocks['TEMPERATURE'].contents['read_temperaturefile'][0])
    except (KeyError, AttributeError) as e:
        # Handle case for hard coded temeperature file in PFLOTRAN
        if os.path.exists('temperature.h5'):
            temperature_files.append('temperature.h5')
            print('temperature.h5 found.')
        else:
            print('No temperature files found in template.')
            temperature_files = ""

    if args.run_type == 'cluster':
        # Run directory preparation script
        # Quick bodge
        for key in config:
            if config[key] == None:
                config[key] = ''
        if type(temperature_files) == list:
            temperature_files = ' '.join(temperature_files)

        env_dict = {
        "CONFIG_PATH": args.path_to_config,
        "DATABASE_NAME": config["database"],
        "AQUEOUS_DATABASE": config["aqueous_database"],
        "CATABOLIC_PATHWAYS": config["catabolic_pathways"],
        "TEMPERATURE_FILES": temperature_files,
        "RESTART_FILE": config["restart_file"],
        "PFLOTRAN": ""}

        if args.pflotran:
            env_dict["PFLOTRAN"] = "TRUE"

        print(env_dict)
        sbatch_command = [
            "sbatch", 
            f"--array=0-{dict_size}",
            f"{path}/rhea/prep_directories.sh"]

        # Run the sbatch command and capture the output
        try:
            # Run the sbatch command
            result = subprocess.run(sbatch_command, check=True, env=env_dict, capture_output=True, text=True)
            
            # Get the job ID from the output
            output = result.stdout
            print("Directory prep command executed successfully.")
            print("Output:", output)
            
            # Assuming output contains something like "Submitted batch job 123456"
            job_id = output.strip().split()[-1]
            print("Job ID:", job_id)
            
            # Wait for the job to complete by checking its status with squeue
            job_running = True
            while job_running:
                # Check the job status using squeue
                squeue_command = ["squeue", "--job", job_id]
                squeue_result = subprocess.run(squeue_command, capture_output=True, text=True)
                
                # If the job is no longer in the queue, squeue returns an empty string
                if job_id not in squeue_result.stdout:
                    job_running = False
                else:
                    # Sleep for a few seconds before checking again
                    print(f"Job {job_id} for directory population is still running. Checking again in 10 seconds...")
                    time.sleep(10)
            
            print(f"Job {job_id} has completed.")

        except subprocess.CalledProcessError as e:
            # Handle the error if sbatch command fails
            print("Error occurred while running sbatch command.")
            print("Return code:", e.returncode)
            print("Error output:", e.stderr)
    
    elif args.run_type == 'local':

        # Quick bodge
        if config['aqueous_database'] == None:
            config['aqueous_database'] = ""
        
        if config['catabolic_pathways'] == None:
            config['catabolic_pathways'] = ""
        if type(temperature_files) == list:
            temperature_files = ' '.join(temperature_files)

        env_dict = {
        "CONFIG_PATH": args.path_to_config,
        "DATABASE_NAME": config["database"],
        "AQUEOUS_DATABASE": config["aqueous_database"],
        "CATABOLIC_PATHWAYS": config["catabolic_pathways"],
        "TEMPERATURE_FILES": temperature_files,
        "RESTART_FILE": config["restart_file"],
        "PFLOTRAN": ""}

        if args.pflotran:
            env_dict["PFLOTRAN"] = "TRUE"

        print(env_dict)
        # Using Parallel to create directories:
        # Get parallel directory
        parallel_exec = subprocess.run('which parallel', shell=True, capture_output=True, text=True)
        parallel_exec = parallel_exec.stdout.strip()

        local_command = (f'{parallel_exec} env SLURM_ARRAY_TASK_ID={{}} {path}/rhea/prep_directories.sh ::: {{0..{dict_size}}}')
        # Run directory preparation script
        subprocess.run(local_command, env=env_dict, shell=True, executable='/bin/zsh')
        
        # Using xargs to create directories:
        # task_ids = [str(i) for i in range(dict_size+1)]
        # task_input = '"'+'\\n'.join(task_ids)+'\\n'+'"'
        # script_path = path + '/rhea/prep_directories.sh'
        # xargs_command = ['echo','-e', str(task_input), '|', 'xargs', '-n', '1', '-P', '4', '-I', '{}', 'env', 'SLURM_ARRAY_TASK_ID={}', script_path]
        # try:
        #  # Start the xargs process
        #     subprocess.run(
        #         ' '.join(xargs_command),
        #         env=env_dict,  # Pass the custom environment variables
        #         shell=True,
        #         executable='/bin/zsh')
        # except Exception as e:
        #     print(f"An error occurred: {e}")

    else:
        print('ERROR: run_type must be either local or cluster')
        sys.exit(1)

    # Print files to prepped directories
    for file in file_dict:
        file_dict[file].path = f'{dir_name}{file}/{config["template"]}'
        file_dict[file].print()
        if file_dict[file].later_inputs:
            for later_file in file_dict[file].later_inputs:
                file_dict[file].later_inputs[later_file].path = f'{dir_name}{file}/{file_dict[file].later_inputs[later_file].path}'
                file_dict[file].later_inputs[later_file].print()

    t_stop = time.time()
    
    print(f'All files generated and directories prepped. Time elapsed: {t_stop - t_start}')
    if args.debug:
        exit('Debug mode: files generated and directories prepped. Exiting before submission.')
    if args.run_type == 'local':
        nodes = config['nodes']
        # Run instances using parallel
        if args.pflotran:
            #subprocess.run([f'parallel -P {nodes} python {path}/rhea/slurm_exec.py -p {{}} {args.path_to_config} ::: {{0..{dict_size}}}'], shell=True, executable='/bin/bash')
            for file in file_dict:
                env = os.environ.copy()
                subprocess.run([f'python {path}/rhea/slurm_exec.py -p {file} {args.path_to_config}'], shell=True, env=env, executable='/bin/zsh')
                print(f'File {file} complete.')
        else:
            #Using Parallel:
            subprocess.run([f'parallel -P {nodes} python {path}/rhea/slurm_exec.py {{}} {args.path_to_config} ::: {{0..{dict_size}}}'], shell=True, executable='/bin/bash')
            
            #Using xargs to run crunchtope in a parallel manner:
            # python_exec = subprocess.run('which python', shell=True, capture_output=True, text=True)
            # python_exec = python_exec.stdout.strip()
            # xargs_command = ['echo','-e', str(task_input), '|', 'xargs', '-n', '1','-P', str(nodes), '-I', '{}', python_exec, path + '/rhea/slurm_exec.py', '{}',  str(args.path_to_config)]
            # subprocess.run(
            #     ' '.join(xargs_command),
            #     env=env_dict,  # Pass the custom environment variables
            #     shell=True,
            #     executable='/bin/zsh')
        # Compile results
        print(dict_size)
        si.compile_results(dict_size+1)

    elif args.run_type == 'cluster':
        submit_runs = f'sbatch --array=0-{dict_size} --export=CONFIG_PATH={args.path_to_config},PFLOTRAN="{args.pflotran}",ALL {path}/rhea/run_input_file.sbatch'
        result = subprocess.run(submit_runs, shell=True)
    else:
        print('ERROR: run_type must be either local or cluster')
