"""Methods for interfacing with slurm."""


def split_dict(dictionary, num):
    """Split a data into n smaller dictionaries to be passed to individual nodes on the cluster.
    Arguments:
    dictionary -- Dictionary to be split.
    num -- number of smaller dictionaries required.
    
    """
    import numpy as np
    from itertools import islice
    it = iter(dictionary)
    quotient = len(dictionary) // num
    remainder = len(dictionary) % num

    if remainder == 0:
        n = quotient
    else:
        n = quotient + 1
    for i in range(0, len(dictionary), n):
        yield {k: dictionary[k] for k in islice(it, n)}


def submit(path_to_config, nodes, number_of_files):
    import subprocess
    import os
    cwd = (os.path.dirname(__file__))
    subprocess.run([f'sbatch', f'-n{nodes}', f'{cwd}/parallel.sbatch'],
                   env=dict(DICT_LEN=str(number_of_files - 1), PATH_TO_CONFIG=path_to_config))


def compile_results(dict_len):
    from context import omphalos
    import omphalos.file_methods as fm
    import numpy as np

    fails = []
    results_dict = dict.fromkeys(np.arange(dict_len))
    for i in results_dict:
        try:
            input_file = fm.unpickle(f'run{i}/input_file{i}_complete.pkl')
            results_dict[i] = input_file
        except:
            fails.append(i)
    
    for j in fails:
        results_dict.pop(j)

    fm.pickle_data_set(results_dict, 'completed_run.pkl')
    print(f'Files failed to run: {len(fails)}')
