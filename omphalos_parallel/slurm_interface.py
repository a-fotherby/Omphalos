"""Methods for interfacing with slurm."""

def split_dict(dictionary, num):
    """Split a data into n smaller dictionaries to be passed to individual nodes on the cluster.
    Arguments:
    dictionary -- Dictionary to be split.
    num -- number of smaller dictionationaries required.
    
    """
    import numpy as np
    from itertools import islice
    it = iter(dictionary)
    quotient = len(dictionary) // num
    remainder = len(dictionary) % num
    
    if remainder == 0:
        n=quotient
    else:
        n=quotient + 1    
    for i in range(0, len(dictionary), n):
        yield {k:dictionary[k] for k in islice(it, n)}
    
def submit(datset_size, nodes, timeout):
    import subprocess
    import os
    cwd = (os.path.dirname(__file__))
    subprocess.run(['sbatch','-n {}'.format(nodes), '{}/parallel.sbatch'.format(cwd)], env=dict(DICT_LEN=str(dataset_size-1), TIMEOUT=str(timeout)))
    
def input_file():
    import omphalos.generate_inputs as gi
    gi.run_input_file()

def compile_results(dict_len):
    from context import omphalos
    import omphalos.file_methods as fm
    import numpy as np
    
    results_dict=dict.fromkeys(np.arange(dict_len))
    for i in results_dict:
        input_file = fm.unpickle('input_file{}_complete.pkl'.format(i), 'tmp{}'.format(i))
        results_dict[i]=input_file

    fm.pickle_data_set(results_dict, 'completed_run.pkl')
