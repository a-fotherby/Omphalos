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
    parser.add_argument('-m', '--min3p', action='store_true')
    parser.add_argument('-d', '--debug', action='store_true')
    parser.add_argument(
        '-c', '--compile-inputs', action='store_true',
        help='After the run, record the parameter values it used in conditions.nc, as '
             'coeus/compile_inputs.py does. CrunchTope local runs only.'
    )
    parser.add_argument(
        '-b', '--backend',
        type=str,
        choices=['xargs', 'parallel'],
        default='xargs',
        help='Parallelization backend: "xargs" (default) or "parallel" (GNU Parallel, which offers '
             'better load balancing and progress reporting where it is installed and working)'
    )
    args = parser.parse_args()

    def run_shell(command, description, env=None, fatal=True):
        """Run a shell command, reporting a non-zero exit rather than carrying on regardless.

        A failed directory-prep step used to surface much later as a FileNotFoundError on the first
        input file, which points at the wrong thing entirely.
        """
        # Augment the environment rather than replacing it: a command run with no PATH resolves
        # executables against os.defpath only, which is how sbatch or parallel go missing.
        full_env = {**os.environ, **env} if env else None
        result = subprocess.run(command, shell=True, executable='/bin/bash', env=full_env)
        if result.returncode != 0:
            message = f'{description} exited with code {result.returncode}.'
            if fatal:
                sys.exit(f'ERROR: {message} Aborting.')
            print(f'WARNING: {message}')
        return result.returncode

    # Settle --compile-inputs before anything runs, so an unsupported combination is known now rather
    # than after a sweep. It reads the per-run pickles the workers leave behind, so it needs runs that
    # have finished: a cluster submission returns as soon as the array is queued. MIN3P and PFLOTRAN
    # describe their parameters differently, so it would have nothing meaningful to read there.
    compile_inputs_wanted = args.compile_inputs
    if args.compile_inputs and args.run_type != 'local':
        print('WARNING: --compile-inputs needs the completed runs, which a cluster submission does '
              'not wait for. Run coeus/compile_inputs.py once the array has finished.')
        compile_inputs_wanted = False
    elif args.compile_inputs and (args.min3p or args.pflotran):
        print(f'WARNING: --compile-inputs reads CrunchTope config blocks, so it does not apply to the '
              f'{"MIN3P" if args.min3p else "PFLOTRAN"} backend. Skipped.')
        compile_inputs_wanted = False

    def compile_input_record(config, results_path=None):
        """Record the parameter values the run used, if asked and supported.

        Named to pair with the results file just written: a second sweep in the same directory writes
        results1.nc, and its record goes to conditions1.nc. Without that, the record would overwrite
        the first sweep's, leaving one sweep's results beside another's parameters — which would join
        silently, both being indexed by run number.

        A failure here does not invalidate the results that were just compiled, so it warns rather
        than exiting.
        """
        if not compile_inputs_wanted:
            return

        from coeus.compile_inputs import compile_inputs
        from core import file_methods as fm

        if results_path is not None:
            output = fm.matching_output_name(results_path)
        else:
            # Nothing was written to pair with, so just avoid clobbering an existing record.
            output = fm.unique_output_path('conditions.nc').name

        try:
            compile_inputs(config, output=output, verbose=False)
        except Exception as exc:  # noqa: BLE001 - the results are already written; do not lose them
            print(f'WARNING: could not compile the input record: {exc}')

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

    if args.min3p:
        from min3p.template import Template
        from min3p import generate_inputs as gi
    elif args.pflotran:
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

    if args.min3p:
        # MIN3P has an isolated local-mode orchestration: it needs neither the
        # database-file copy nor the temperature/restart machinery that the
        # CrunchTope/PFLOTRAN prep script performs (MIN3P reads an absolute
        # database directory baked into each input file by generate_inputs).
        # This branch therefore bypasses prep_directories.sh entirely, leaving
        # the existing backends' code path untouched.
        if args.run_type != 'local':
            sys.exit('ERROR: MIN3P backend currently supports only run_type "local" in rhea.')

        file_dict = gi.configure_input_files(template, 'foo', rhea=True)
        dict_size = len(file_dict) - 1
        dir_name = 'run'
        t_start = time.time()

        # Create run directories and print each input file into its own dir.
        for f in file_dict:
            Path(f'{dir_name}{f}').mkdir(exist_ok=True)
            file_dict[f].path = f'{dir_name}{f}/{config["template"]}'
            file_dict[f].print()

        if args.debug:
            sys.exit('Debug mode: MIN3P input files generated. Exiting before running.')

        # Run each file through MIN3P via slurm_exec.py using the chosen backend.
        slurm_exec_script = _rhea_dir / 'slurm_exec.py'
        nodes = config.get('nodes', 1)
        if args.backend == 'parallel':
            result = subprocess.run('which parallel', shell=True, capture_output=True, text=True)
            parallel_exec = result.stdout.strip()
            if not parallel_exec:
                print('ERROR: GNU Parallel not found. Install it or use --backend xargs')
                sys.exit(1)
            run_command = (
                f'{parallel_exec} -P {nodes} python {slurm_exec_script} -m {{}} '
                f'{args.path_to_config} ::: {{0..{dict_size}}}'
            )
        else:  # xargs
            run_command = (
                f'seq 0 {dict_size} | xargs -I {{}} -P {nodes} '
                f'python {slurm_exec_script} -m {{}} {args.path_to_config}'
            )
        # A non-zero exit here means the runner itself struggled; individual simulation failures are
        # recorded per run and reported by compile_results, so keep going and let it account for them.
        run_shell(run_command, 'MIN3P run command', fatal=False)

        summary = si.compile_results(dict_size + 1, simulator='min3p')
        compile_input_record(config, results_path=summary['results'])
        t_stop = time.time()
        print(f'MIN3P files compiled: {summary["compiled"]} of {summary["total"]}. '
              f'Time elapsed: {t_stop - t_start}')
        sys.exit(0 if summary['compiled'] else 1)

    if is_staged:
        staged_file_dict = gi.configure_staged_input_files(template, 'foo', rhea=True)
        dict_size = len(staged_file_dict) - 1
    else:
        file_dict = gi.configure_input_files(template, 'foo', rhea=True)
        dict_size = len(file_dict) - 1
    # Start timer for directory preparation and submission
    t_start = time.time()

    # Every file the runs need beside their input decks and databases: the spatial fields CrunchTope
    # reads from disk. This used to look for read_temperaturefile alone, so a deck reading porosity,
    # saturation, tortuosity or permeability from a file ran without it. It also reads the config,
    # because a restart_chain naming a porosity file per stage names files that appear in no
    # template block.
    # Only the CrunchTope backend describes its auxiliary files this way; a PFLOTRAN template has no
    # keyword blocks to read, and falls through to the hardcoded temperature file below as before.
    aux_files = gi.support_files(template, config) if hasattr(gi, 'support_files') else []
    if aux_files:
        print(f'Auxiliary files found: {aux_files}')
    elif Path('temperature.h5').exists():
        # PFLOTRAN hardcodes this one rather than naming it in the deck.
        aux_files = ['temperature.h5']
        print('temperature.h5 found.')
    else:
        print('No auxiliary files found in template or config.')

    # Script paths using pathlib
    prep_script = _rhea_dir / 'prep_directories.sh'
    slurm_exec_script = _rhea_dir / 'slurm_exec.py'
    run_sbatch = _rhea_dir / 'run_input_file.sbatch'

    if args.run_type == 'cluster':
        # Run directory preparation script
        for key in config:
            if config[key] is None:
                config[key] = ''

        env_dict = {
            "CONFIG_PATH": args.path_to_config,
            "DATABASE_NAME": config["database"],
            "AQUEOUS_DATABASE": config["aqueous_database"],
            "CATABOLIC_PATHWAYS": config["catabolic_pathways"],
            "AUX_FILES": ' '.join(aux_files),
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

        # Run the sbatch command and capture the output. The environment is augmented rather than
        # replaced, or sbatch itself may not be found: with no PATH, subprocess resolves executables
        # against os.defpath alone.
        try:
            result = subprocess.run(sbatch_command, check=True, env={**os.environ, **env_dict},
                                    capture_output=True, text=True)

            output = result.stdout
            print("Directory prep command executed successfully.")
            print("Output:", output)

            import re as _re
            match = _re.search(r'Submitted batch job (\d+)', output)
            if not match:
                raise RuntimeError(
                    f"Could not parse SLURM job ID from sbatch output: {output!r}"
                )
            job_id = match.group(1)
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
        except FileNotFoundError:
            # No sbatch on PATH: cluster mode was asked for off a cluster, which is worth saying
            # plainly rather than as a traceback.
            sys.exit('ERROR: sbatch not found. Cluster mode needs a SLURM scheduler; '
                     'use run_type "local" on a workstation.')

    elif args.run_type == 'local':
        if config['aqueous_database'] is None:
            config['aqueous_database'] = ""

        if config['catabolic_pathways'] is None:
            config['catabolic_pathways'] = ""

        env_dict = {
            "CONFIG_PATH": args.path_to_config,
            "DATABASE_NAME": config["database"],
            "AQUEOUS_DATABASE": config["aqueous_database"],
            "CATABOLIC_PATHWAYS": config["catabolic_pathways"],
            "AUX_FILES": ' '.join(aux_files),
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
        run_shell(prep_command, 'Directory preparation', env=env_dict)

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
                run_shell(f'python {slurm_exec_script} -p {file} {args.path_to_config}',
                          f'PFLOTRAN run of file {file}', fatal=False)
                print(f'File {file} complete.')
        else:
            run_command = build_run_command(args.backend, slurm_exec_script, dict_size, nodes, args.path_to_config, parallel_exec)
            # Individual simulation failures are recorded per run and reported by compile_results, so
            # a non-zero exit here is a warning rather than a reason to stop before compiling.
            run_shell(run_command, 'Run command', fatal=False)

        # Compile results. compile_results reports the per-run breakdown itself; exit non-zero if
        # nothing came back, so a wholly failed sweep does not look like a success to a caller.
        summary = si.compile_results(dict_size + 1)
        compile_input_record(config, results_path=summary['results'])
        if not summary['compiled']:
            sys.exit(1)

    elif args.run_type == 'cluster':
        # No compile_input_record here: --compile-inputs is refused for cluster runs up front, since
        # the array has not finished by the time this returns.
        # OMPHALOS_DIR tells the batch script where this checkout lives, so it need not hardcode a path.
        submit_runs = (
            f'sbatch --array=0-{dict_size} '
            f'--export=CONFIG_PATH={args.path_to_config},PFLOTRAN="{args.pflotran}",'
            f'OMPHALOS_DIR={_project_root},ALL {run_sbatch}'
        )
        run_shell(submit_runs, 'Submitting run array')
    else:
        print('ERROR: run_type must be either local or cluster')
