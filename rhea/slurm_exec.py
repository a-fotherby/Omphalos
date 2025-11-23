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


def execute(file_num, config, pflo):
    """Execute a single input file.

    Args:
        file_num: File number to run
        config: Configuration dictionary
        pflo: Whether to use PFLOTRAN mode

    Returns:
        InputFile object with results
    """
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
    tmp_dir = Path(f'run{file_num}')

    # overwrite config['template'] entry to fix file reading
    # same for other files that must be read in
    config.update({'template': str(cwd / tmp_dir / name)})
    if aqueous_database is not None:
        config.update({'aqueous_database': str(cwd / tmp_dir / aqueous_database)})
    if catabolic_pathways is not None:
        config.update({'catabolic_pathways': str(cwd / tmp_dir / catabolic_pathways)})

    input_file = Template(config)
    input_file.path = Path(config['template'])

    if pflo:
        run.pflotran(input_file, file_num, config['timeout'], str(tmp_dir))
    else:
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
    args = parser.parse_args()

    if args.pflotran:
        import pflotran.file_methods as fm
    else:
        import omphalos.file_methods as fm

    with open(args.config_path) as file:
        config = yaml.safe_load(file)

    input_file = execute(args.file_num, config, args.pflotran)
    print(f'File {args.file_num} returned to __main__.')

    fm.pickle_data_set(input_file, f'run{args.file_num}/input_file{args.file_num}_complete.pkl')
