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


def compile_results(dict_len, simulator='crunchtope'):
    """Compile results from distributed runs.

    A run can fail in two ways: it can return nothing at all (no pickle to read, e.g. the worker
    was killed), or it can come back carrying a non-zero ``error_code`` set by the simulator wrapper
    (a timeout, a convergence failure, a missing input file). Only runs that returned cleanly hold
    results worth compiling, so the others are counted, reported and left out of the results file.

    Args:
        dict_len: Number of input files that were run
        simulator: Backend that produced the results ('crunchtope', 'pflotran',
            or 'min3p'). Selects the ``dataset_to_netcdf`` behaviour.

    Returns:
        dict: Summary of the run with keys 'total', 'compiled', 'no_output' (list of run numbers
        that returned nothing) and 'errors' ({run number: error code} for runs that failed).
    """
    from core import file_methods as fm

    no_output = []
    errors = {}
    results_dict = {}

    for i in range(dict_len):
        try:
            input_file = fm.unpickle(f'run{i}/input_file{i}_complete.pkl')
        except Exception:
            no_output.append(i)
            continue

        error_code = getattr(input_file, 'error_code', 0)
        if error_code:
            errors[i] = error_code
        else:
            results_dict[i] = input_file

    if results_dict:
        fm.dataset_to_netcdf(results_dict, simulator=simulator)
        for file in results_dict:
            del results_dict[file].results
    else:
        print('WARNING: no run returned usable output, so no results file was written.')

    print(f'Files compiled: {len(results_dict)} of {dict_len}.')
    if no_output:
        print(f'Files that returned no output ({len(no_output)}): {no_output}')
    if errors:
        print(f'Files that failed during the run ({len(errors)}), as run: error_code: {errors}')

    return {'total': dict_len, 'compiled': len(results_dict), 'no_output': no_output,
            'errors': errors}
