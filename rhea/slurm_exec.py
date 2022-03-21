"""Script to run Omphalos inside slurm.
Expects command line args in order

dict_name -- name of the pickle file where the data has been stored as *.pickle
tmp_dir -- temporary directory for running input files. Must be unique.

"""
from context import omphalos


def execute(file_num, config):
    import signal
    import subprocess
    import omphalos.results as results
    import omphalos.file_methods as fm
    from omphalos.template import Template
    import omphalos.run as run

    name = f'{config["template"]}{file_num}'
    tmp_dir = f'run{file_num}'
    input_file = Template(f'tmp_dir/{name}')

    signal.signal(signal.SIGALRM, run.timeout_handler)
    signal.alarm(int(config['timeout']))
    try:
        run.crunchtope(f'{name}.in', tmp_dir)
    except Exception:
        print(f'File {file_num} timed out.')
        input_file.timeout = True
        # Leave faulty input file behind for inspection.
        subprocess.run(['rm', "*.tec", '*.out'], cwd=tmp_dir)
        return input_file

    signal.alarm(0)
    print(f'File {file_num} alarm disarmed')

    # Make a results object that is an attribute of the InputFile object.
    input_file.results = results.Results()
    print(f'File {file_num} results object created.')

    output_categories = fm.get_data_cats(tmp_dir)
    for output in output_categories:
        input_file.results.get_output(tmp_dir, output)

    print(f'File {file_num} outputs recorded.')
    print(f'File {file_num} about to clean.')

    # Clean the temp directory.
    subprocess.run(['rm', '*.tec', '*.out', '*.in'], cwd=tmp_dir)
    print(f'File {file_num} directory cleaned. Returning input file object to main thread.')

    return input_file


if __name__ == '__main__':
    import argparse
    import omphalos.file_methods as fm
    import yaml

    parser = argparse.ArgumentParser()
    parser.add_argument("file_num", help="Input file dict key.")
    parser.add_argument("config_path", help="Omphalos config file.")
    args = parser.parse_args()

    with open(args.config_path) as file:
        config = yaml.full_load(file)

    input_file = execute(args.file_num, config)
    print(f'File {args.file_num} returned to __main__.')

    # Hotwired directory name for now as it hasn't been passed through for now.
    fm.pickle_data_set(input_file, f'run{args.file_num}/input_file{args.file_num}_complete.pkl')

    print(f'File {args.file_num} pickled.')

    if input_file.timeout:
        print(f'File {args.file_num} timed-out.')
    else:
        print(f'File {args.file_num} completed.')
