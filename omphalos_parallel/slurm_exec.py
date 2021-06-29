"""Script to run Omphalos inside slurm.
Expects command line args in order

dict_name -- name of the pickle file where the data has been stored as *.pickle
tmp_dir -- temporary directory for running input files. Must be unique.

"""
from context import omphalos

def execute(file_num, timeout):
    import signal
    import subprocess
    import time
    import omphalos.results as results
    import omphalos.file_methods as fm
    import omphalos.generate_inputs as gi
    import omphalos.run as run
    
    # Hard coded for now...
    name = 'input_file'
    tmp_dir = f'run{file_num}/'
    input_file = gi.import_template(f'{tmp_dir}/{name}.in')
    
    signal.signal(signal.SIGALRM, run.timeout_handler)
    signal.alarm(int(timeout))
    try:
        run.crunchtope(f'{name}.in', tmp_dir)
    except Exception:
        print(f'File {file_num} timed out.')
        input_file.timeout = True
        # Leave faulty input file behind for inspection.
        subprocess.run(['rm', "*.tec", '*.out'], cwd=tmp_dir)
        return input_file

    signal.alarm(0)

    # Make a results object that is an attribute of the InputFile object.
    input_file.results = results.Results()

    output_categories = fm.get_data_cats(tmp_dir)
    for output in output_categories:
        input_file.results.get_output(tmp_dir, output)

    # Clean the temp directory.
    subprocess.run(['rm', '*.tec', '*.out', '*.in'], cwd=tmp_dir)
    
    return input_file


if __name__ == '__main__':
    import argparse              
    import omphalos.file_methods as fm
    parser = argparse.ArgumentParser()
    parser.add_argument("file_num", help="Input file dict key.")
    parser.add_argument("timeout", help="Timeout for CT file.")
    args = parser.parse_args()
    
    input_file = execute(args.file_num, args.timeout)
    # Hotwired directory name for now as it hasn't been passed through for now.
    fm.pickle_data_set(input_file, f'run{args.file_num}/input_file{args.file_num}_complete.pkl')

    if input_file.timeout == True:
        print(f'File #{args.file_num} timed-out.')
    else:
        print(f'File #{args.file_num} completed.')
