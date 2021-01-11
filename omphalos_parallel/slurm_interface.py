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
    
def submit(data_set, nodes):
    import subprocess
    import os
    os.environ['DICT_END'] = str(len(data_set) - 1)
    os.environ['NODES'] = str(nodes)
    cwd = (os.path.dirname(__file__))
    subprocess.run(['sbatch', '{}/parallel.sbatch'.format(cwd)])
    
def input_file():
    import omphalos.generate_inputs as gi
    gi.run_input_file()