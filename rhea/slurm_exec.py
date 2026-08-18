"""Script to run Omphalos inside slurm.

Expects command line args in order:
    file_num -- the file number to run
    config_path -- path to the Omphalos config file
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


def _restore_logk_record(input_file, directory):
    """Carry a per-run log K recomputation's settings onto the InputFile that gets pickled.

    This worker rebuilds its InputFile from the run directory rather than receiving the object
    configure_input_files decorated, so the settings would otherwise be lost between generating the
    database and recording what produced it. Every other swept value survives because it is in a
    file the worker re-reads; the pressure a database was computed at is in no file, because a
    CrunchTope database has nowhere to put it. Hence the sidecar.

    Absent for every sweep that does not vary a recomputation setting, which is almost all of them.
    """
    import json

    import omphalos.run as omphalos_run

    record = Path(directory) / omphalos_run.LOGK_RECORD

    if record.exists():
        with open(record) as file:
            input_file.logk_settings = json.load(file)


def execute(file_num, config, pflo, min3p=False):
    """Execute a single input file.

    Args:
        file_num: File number to run
        config: Configuration dictionary
        pflo: Whether to use PFLOTRAN mode
        min3p: Whether to use MIN3P mode

    Returns:
        InputFile object with results
    """
    if min3p:
        print("Running in MIN3P mode")
        import min3p.run as run
        from min3p.template import Template

        cwd = Path.cwd()
        # The basename, not the config value: joining an absolute template path onto the run
        # directory yields the template itself, so every run would re-read the unswept deck.
        name = Path(config['template']).name
        tmp_dir = Path(f'run{file_num}')
        config.update({'template': str(cwd / tmp_dir / name)})

        input_file = Template(config)
        input_file.path = Path(config['template'])
        binary = config.get('min3p_binary', run.MIN3P_BINARY)
        # run.input_file (re)writes the input file + root.dat into the run dir,
        # invokes MIN3P, and parses the outputs into input_file.results.
        run.input_file(input_file, file_num, str(tmp_dir), config['timeout'], binary=binary)
        return input_file

    if pflo:
        print("Running in PFLOTRAN mode")
        import pflotran.file_methods as fm
        from pflotran.template import Template
        import pflotran.run as run
    else:
        print("Running in CrunchTope mode")
        import omphalos.run as run
        import omphalos.file_methods as fm
        from omphalos.template import Template

    cwd = Path.cwd()
    name = config['template']
    aqueous_database = config['aqueous_database']
    catabolic_pathways = config['catabolic_pathways']
    database = config.get('database')
    tmp_dir = Path(f'run{file_num}')

    # overwrite config['template'] entry to fix file reading
    # same for other files that must be read in
    config.update({'template': str(cwd / tmp_dir / name)})
    if aqueous_database is not None:
        config.update({'aqueous_database': str(cwd / tmp_dir / aqueous_database)})
    if catabolic_pathways is not None:
        config.update({'catabolic_pathways': str(cwd / tmp_dir / catabolic_pathways)})
    # The run directory's database is this run's own, swept copy; the one the config names sits in
    # the working directory and is the template's. Reading the latter here would hand every run the
    # unswept file, and _print_aux_files would then write it over the swept one.
    if database:
        config.update({'database': str(cwd / tmp_dir / database)})

    # The databases in the run directory already have their log K columns recomputed: rhea/main.py
    # did it before generating anything -- once on the template where every setting is fixed, or
    # once per run where one is swept. Either way the answer is already in the file, and redoing it
    # here would repeat the whole calculation for every run in the sweep.
    config.update({'recompute_log_k': False, 'add_isotopes': False})

    # Check for staged restart runs
    if not pflo and 'restart_chain' in config and config['restart_chain']:
        print(f"Running staged execution for run {file_num}")
        num_stages = config['restart_chain']['stages']
        base_name = name.rsplit('.', 1)[0]
        ext = name.rsplit('.', 1)[1] if '.' in name else 'in'

        # Build stages_dict by reading pre-printed staged input files
        stages_dict = {}
        for stage_num in range(num_stages):
            stage_path = str(cwd / tmp_dir / f'{base_name}_stage{stage_num}.{ext}')
            stage_config = config.copy()
            stage_config['template'] = stage_path
            stage_config['restart'] = True  # Prevent Template from importing later_inputfiles

            # A 'staged' sweep gives each stage its own auxiliary files, which rhea/main.py wrote
            # into a directory per stage. Reading the run directory's copies instead would hand
            # every stage the same ones -- in practice stage 0's, since that is what runs first --
            # and the staged values of everything in them would be silently discarded.
            stage_aux = cwd / tmp_dir / f'stage{stage_num}_aux'

            if stage_aux.is_dir():
                for key, filename in (('database', database),
                                      ('aqueous_database', aqueous_database),
                                      ('catabolic_pathways', catabolic_pathways)):
                    if filename and (stage_aux / filename).exists():
                        stage_config[key] = str(stage_aux / filename)

            stage_file = Template(stage_config)
            stage_file.file_num = int(file_num)
            stage_file.stage_num = stage_num
            _restore_logk_record(stage_file, stage_aux if stage_aux.is_dir() else cwd / tmp_dir)
            stage_file.later_inputs = {}  # Clear any later_inputs, stages are handled separately
            stages_dict[stage_num] = stage_file

        input_file = run.run_staged_input(stages_dict, int(file_num), str(tmp_dir), config['timeout'])
    else:
        input_file = Template(config)
        input_file.path = Path(config['template'])
        _restore_logk_record(input_file, cwd / tmp_dir)

        if pflo:
            run.pflotran(input_file, file_num, config['timeout'], str(tmp_dir))
        else:
            # Write the auxiliary namelists out before running, as the sequential path
            # (run.input_file) and the staged path (run.run_staged_input) both do. Without
            # this, a deck needing CatabolicPathways.in never gets one, and -- silently --
            # a sweep of the 'namelists:' section runs every file against the unmodified
            # aqueous database, because the only copy in the run directory is the verbatim
            # one prep_directories.sh placed there.
            run._print_aux_files(input_file, Path(tmp_dir).resolve())
            run.crunchtope(input_file, file_num, config['timeout'], str(tmp_dir))

    return input_file


if __name__ == '__main__':
    import argparse
    import yaml
    import site
    site.addsitedir(site.getusersitepackages())

    parser = argparse.ArgumentParser()
    parser.add_argument("file_num", help="Input file dict key.")
    parser.add_argument("config_path", help="Omphalos config file.")
    parser.add_argument('-p', '--pflotran', action='store_true')
    parser.add_argument('-m', '--min3p', action='store_true')
    args = parser.parse_args()

    if args.pflotran:
        import pflotran.file_methods as fm
    else:
        # core.file_methods provides pickle_data_set for CrunchTope and MIN3P.
        from core import file_methods as fm

    with open(args.config_path) as file:
        config = yaml.safe_load(file)

    input_file = execute(args.file_num, config, args.pflotran, min3p=args.min3p)
    print(f'File {args.file_num} returned to __main__.')

    fm.pickle_data_set(input_file, f'run{args.file_num}/input_file{args.file_num}_complete.pkl')
