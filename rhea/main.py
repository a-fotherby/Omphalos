"""Run Omphalos in parallel using Slurm.

Args:
    config -- specifies YAML file containing template modification options.
"""

if __name__ == '__main__':
    import argparse
    import os
    import subprocess
    import sys
    import time
    from pathlib import Path

    # Get paths using pathlib
    _rhea_dir = Path(__file__).resolve().parent
    _project_root = _rhea_dir.parent

    # Add project root to path
    if str(_project_root) not in sys.path:
        sys.path.insert(0, str(_project_root))

    import yaml
    from rhea import slurm_interface as si

    parser = argparse.ArgumentParser()
    parser.add_argument('path_to_config', type=str, help='YAML file containing options.')
    parser.add_argument('run_type', type=str, help='Type of run, either local or cluster.')
    parser.add_argument('-p', '--pflotran', action='store_true')
    parser.add_argument('-d', '--debug', action='store_true')
    parser.add_argument(
        '-b', '--backend',
        type=str,
        choices=['parallel', 'xargs'],
        default='parallel',
        help='Parallelization backend: "parallel" (GNU Parallel, default) or "xargs"'
    )
    args = parser.parse_args()

    def build_prep_command(backend, prep_script, dict_size, parallel_exec=None):
        """Build the directory preparation command for the chosen backend."""
        if backend == 'parallel':
            return f'{parallel_exec} env SLURM_ARRAY_TASK_ID={{}} {prep_script} ::: {{0..{dict_size}}}'
        else:  # xargs
            return f'seq 0 {dict_size} | xargs -I {{}} -P 0 env SLURM_ARRAY_TASK_ID={{}} {prep_script}'

    def build_run_command(backend, slurm_exec_script, dict_size, nodes, config_path, parallel_exec=None):
        """Build the simulation execution command for the chosen backend."""
        if backend == 'parallel':
            return f'{parallel_exec} -P {nodes} python {slurm_exec_script} {{}} {config_path} ::: {{0..{dict_size}}}'
        else:  # xargs
            return f'seq 0 {dict_size} | xargs -I {{}} -P {nodes} python {slurm_exec_script} {{}} {config_path}'

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

    # Check for staged restart runs
    is_staged = 'restart_chain' in config and config['restart_chain']

    if is_staged:
        staged_file_dict = gi.configure_staged_input_files(template, 'foo', rhea=True)
        dict_size = len(staged_file_dict) - 1
    else:
        file_dict = gi.configure_input_files(template, 'foo', rhea=True)
        dict_size = len(file_dict) - 1
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
    except (KeyError, AttributeError):
        # Handle case for hard coded temperature file in PFLOTRAN
        if Path('temperature.h5').exists():
            temperature_files.append('temperature.h5')
            print('temperature.h5 found.')
        else:
            print('No temperature files found in template.')
            temperature_files = ""

    # Script paths using pathlib
    prep_script = _rhea_dir / 'prep_directories.sh'
    slurm_exec_script = _rhea_dir / 'slurm_exec.py'
    run_sbatch = _rhea_dir / 'run_input_file.sbatch'

    if args.run_type == 'cluster':
        # Run directory preparation script
        for key in config:
            if config[key] is None:
                config[key] = ''
        if isinstance(temperature_files, list):
            temperature_files = ' '.join(temperature_files)

        env_dict = {
            "CONFIG_PATH": args.path_to_config,
            "DATABASE_NAME": config["database"],
            "AQUEOUS_DATABASE": config["aqueous_database"],
            "CATABOLIC_PATHWAYS": config["catabolic_pathways"],
            "TEMPERATURE_FILES": temperature_files,
            "RESTART_FILE": config.get("restart_file") or "",
            "PFLOTRAN": ""
        }

        if args.pflotran:
            env_dict["PFLOTRAN"] = "TRUE"

        print(env_dict)
        sbatch_command = [
            "sbatch",
            f"--array=0-{dict_size}",
            str(prep_script)
        ]

        # Run the sbatch command and capture the output
        try:
            result = subprocess.run(sbatch_command, check=True, env=env_dict, capture_output=True, text=True)

            output = result.stdout
            print("Directory prep command executed successfully.")
            print("Output:", output)

            # Assuming output contains something like "Submitted batch job 123456"
            job_id = output.strip().split()[-1]
            print("Job ID:", job_id)

            # Wait for the job to complete by checking its status with squeue
            job_running = True
            while job_running:
                squeue_command = ["squeue", "--job", job_id]
                squeue_result = subprocess.run(squeue_command, capture_output=True, text=True)

                if job_id not in squeue_result.stdout:
                    job_running = False
                else:
                    print(f"Job {job_id} for directory population is still running. Checking again in 10 seconds...")
                    time.sleep(10)

            print(f"Job {job_id} has completed.")

        except subprocess.CalledProcessError as e:
            print("Error occurred while running sbatch command.")
            print("Return code:", e.returncode)
            print("Error output:", e.stderr)

    elif args.run_type == 'local':
        if config['aqueous_database'] is None:
            config['aqueous_database'] = ""

        if config['catabolic_pathways'] is None:
            config['catabolic_pathways'] = ""
        if isinstance(temperature_files, list):
            temperature_files = ' '.join(temperature_files)

        env_dict = {
            "CONFIG_PATH": args.path_to_config,
            "DATABASE_NAME": config["database"],
            "AQUEOUS_DATABASE": config["aqueous_database"],
            "CATABOLIC_PATHWAYS": config["catabolic_pathways"],
            "TEMPERATURE_FILES": temperature_files,
            "RESTART_FILE": config.get("restart_file") or "",
            "PFLOTRAN": ""
        }

        if args.pflotran:
            env_dict["PFLOTRAN"] = "TRUE"

        print(env_dict)

        # Get parallel executable path if using GNU Parallel backend
        parallel_exec = None
        if args.backend == 'parallel':
            result = subprocess.run('which parallel', shell=True, capture_output=True, text=True)
            parallel_exec = result.stdout.strip()
            if not parallel_exec:
                print('ERROR: GNU Parallel not found. Install it or use --backend xargs')
                sys.exit(1)

        # Run directory preparation script
        prep_command = build_prep_command(args.backend, prep_script, dict_size, parallel_exec)
        subprocess.run(prep_command, env=env_dict, shell=True, executable='/bin/zsh')

    else:
        print('ERROR: run_type must be either local or cluster')
        sys.exit(1)

    # Print files to prepped directories
    if is_staged:
        # Print staged input files - one file per stage per run
        for run_num in staged_file_dict:
            for stage_num in staged_file_dict[run_num]:
                stage_file = staged_file_dict[run_num][stage_num]
                # Name files by stage: template_stage0.in, template_stage1.in, etc.
                base_name = config["template"].rsplit('.', 1)[0]
                ext = config["template"].rsplit('.', 1)[1] if '.' in config["template"] else 'in'
                stage_file.path = f'{dir_name}{run_num}/{base_name}_stage{stage_num}.{ext}'
                stage_file.print()
    else:
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
        sys.exit('Debug mode: files generated and directories prepped. Exiting before submission.')

    if args.run_type == 'local':
        nodes = config['nodes']
        # Run instances using chosen backend
        if args.pflotran:
            if is_staged:
                print('ERROR: Staged restart runs are not supported for PFLOTRAN mode.')
                sys.exit(1)
            # PFLOTRAN runs sequentially due to specific requirements
            for file in file_dict:
                env = os.environ.copy()
                subprocess.run([f'python {slurm_exec_script} -p {file} {args.path_to_config}'], shell=True, env=env, executable='/bin/zsh')
                print(f'File {file} complete.')
        else:
            run_command = build_run_command(args.backend, slurm_exec_script, dict_size, nodes, args.path_to_config, parallel_exec)
            subprocess.run(run_command, shell=True, executable='/bin/bash')

        # Compile results
        print(dict_size)
        si.compile_results(dict_size + 1)

    elif args.run_type == 'cluster':
        submit_runs = f'sbatch --array=0-{dict_size} --export=CONFIG_PATH={args.path_to_config},PFLOTRAN="{args.pflotran}",ALL {run_sbatch}'
        subprocess.run(submit_runs, shell=True)
    else:
        print('ERROR: run_type must be either local or cluster')
