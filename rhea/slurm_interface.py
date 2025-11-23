"""Methods for interfacing with slurm."""

import subprocess
import sys
from pathlib import Path

# Add parent directory to path for imports
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


def split_dict(dictionary, num):
    """Split a data into n smaller dictionaries to be passed to individual nodes on the cluster.

    Args:
        dictionary: Dictionary to be split.
        num: Number of smaller dictionaries required.

    Yields:
        Smaller dictionaries
    """
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
    """Submit a job to the SLURM scheduler.

    Args:
        path_to_config: Path to the configuration file
        nodes: Number of nodes to use
        number_of_files: Total number of files to process
    """
    # Get the directory containing this file
    rhea_dir = Path(__file__).resolve().parent
    sbatch_script = rhea_dir / 'parallel.sbatch'

    subprocess.run(
        ['sbatch', f'-n{nodes}', str(sbatch_script)],
        env=dict(DICT_LEN=str(number_of_files), PATH_TO_CONFIG=path_to_config)
    )


def compile_results(dict_len):
    """Compile results from distributed runs.

    Args:
        dict_len: Number of input files that were run
    """
    import numpy as np
    import omphalos.file_methods as fm

    fails = []
    results_dict = dict.fromkeys(np.arange(dict_len))

    for i in results_dict:
        try:
            input_file = fm.unpickle(f'run{i}/input_file{i}_complete.pkl')
            results_dict[i] = input_file
        except Exception:
            fails.append(i)

    for j in fails:
        results_dict.pop(j)

    fm.dataset_to_netcdf(results_dict)

    for file in results_dict:
        del results_dict[file].results

    print(f'Files failed to run: {len(fails)}')
