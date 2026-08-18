"""Main entry point for running MIN3P sweeps sequentially.

Usage::

    python -m min3p.main config.yaml output_name.pkl [-d]

Mirrors ``omphalos/main.py``: parse a template, generate the input-file dataset
from the config, run each through MIN3P, and pickle the resulting InputFile
records (with their parsed output datasets attached).
"""

if __name__ == '__main__':
    import argparse
    import sys
    from pathlib import Path

    _project_root = Path(__file__).resolve().parent.parent
    if str(_project_root) not in sys.path:
        sys.path.insert(0, str(_project_root))

    import yaml

    from core import file_methods as core_fm
    from min3p import generate_inputs as gi
    from min3p import run
    from min3p.template import Template

    parser = argparse.ArgumentParser(description='Run a MIN3P parameter sweep.')
    parser.add_argument('config_path', type=str, help='YAML file containing options.')
    parser.add_argument('output_name', type=str, help='Output pickle file name.')
    parser.add_argument('-d', '--debug', action='store_true',
                        help='Generate input files without running MIN3P.')
    args = parser.parse_args()

    tmp_dir = Path('tmp')
    tmp_dir.mkdir(exist_ok=True)

    with open(args.config_path) as f:
        config = yaml.safe_load(f)

    print('*** Importing template file ***')
    template = Template(config)

    binary = config.get('min3p_binary', run.MIN3P_BINARY)
    is_staged = bool(config.get('restart_chain'))

    print('*** Generating input files ***')
    if is_staged:
        staged = gi.configure_staged_input_files(template, str(tmp_dir) + '/')
    else:
        file_dict = gi.configure_input_files(template, str(tmp_dir) + '/')

    if args.debug:
        print('*** DEBUG MODE: FILES NOT RUN ***')
        stem = Path(config['template']).stem
        if is_staged:
            for run_num in staged:
                for stage in staged[run_num]:
                    sf = staged[run_num][stage]
                    sf.path = tmp_dir / f'{stem}_{run_num}_stage{stage}.dat'
                    sf.print()
        else:
            for f in file_dict:
                file_dict[f].path = tmp_dir / f'{stem}_{f}.dat'
                file_dict[f].print()
        sys.exit()

    print('*** Begin running input files... ***')
    # The deck is run away from where it was read, so the auxiliary files it reads by run name
    # (.hyc, .ivs, .bcvs and the rest) have to travel with it.
    from min3p import file_methods as min3p_fm

    if is_staged:
        # Each run's stages execute sequentially in a per-run subdirectory so
        # their restart.tmp state files do not collide across runs.
        file_dict = {}
        for run_num in staged:
            run_dir = tmp_dir / f'run{run_num}'
            run_dir.mkdir(parents=True, exist_ok=True)
            min3p_fm.copy_auxiliary_files(config['template'], run_dir)
            file_dict[run_num] = run.run_staged(
                staged[run_num], run_num, str(run_dir), config['timeout'], binary=binary
            )
    else:
        min3p_fm.copy_auxiliary_files(config['template'], tmp_dir)
        run.run_dataset(file_dict, str(tmp_dir), config['timeout'], binary=binary)

    print('*** Writing results to results.nc ***')
    core_fm.dataset_to_netcdf(file_dict, simulator='min3p')

    # Drop bulky result datasets before pickling the InputFile records; the
    # numerical data now lives in results.nc.
    for f in file_dict:
        file_dict[f].results = {}

    print(f'*** Writing InputFile record to {args.output_name} ***')
    core_fm.pickle_data_set(file_dict, args.output_name)
    print('*** Run complete ***')
