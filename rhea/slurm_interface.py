"""Methods for interfacing with slurm."""

import re
import shutil
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

    Note: nothing in rhea currently calls this. Cluster runs go through rhea/main.py, which submits
    prep_directories.sh and run_input_file.sbatch directly.

    Args:
        path_to_config: Path to the configuration file
        nodes: Number of nodes to use
        number_of_files: Total number of files to process
    """
    import os

    # Get the directory containing this file
    rhea_dir = Path(__file__).resolve().parent
    sbatch_script = rhea_dir / 'parallel.sbatch'

    # Augment the environment rather than replacing it, or sbatch itself may not be found, and pass
    # the checkout location so the batch scripts need not hardcode a path.
    env = {**os.environ,
           'DICT_LEN': str(number_of_files),
           'PATH_TO_CONFIG': path_to_config,
           'OMPHALOS_DIR': str(rhea_dir.parent)}

    subprocess.run(['sbatch', f'-n{nodes}', str(sbatch_script)], env=env)


def _spill_results(input_file, run_num, spill_dir):
    """Move a run's parsed results out of memory and into a netCDF file in spill_dir.

    Returns the input_file, with its results replaced by a lazy view of the spilled file. Left
    untouched if there is nothing dict-shaped to spill: PFLOTRAN keeps a single Dataset in results
    rather than a mapping of categories.
    """
    from coeus.helper import fix_smalls
    from core import file_methods as fm

    if not isinstance(input_file.results, dict) or not input_file.results:
        return input_file

    spill_path = Path(spill_dir) / f'results_{run_num}.nc'
    categories = list(input_file.results)

    for category in categories:
        # Repair CrunchTope's unprintable small numbers here, while the arrays are still in memory
        # and writable: netCDF cannot store the mixed dtypes they arrive as.
        fix_smalls({run_num: input_file}, category)
        # The spill is a netCDF file like any other, so a name netCDF forbids stops it here rather
        # than at the results file the final writer renames for. Every MIN3P sweep carries one
        # ('C-Alk [eq/L]'), which made this the step that ended them.
        input_file.results[category] = fm.sanitise_netcdf_names(input_file.results[category])
        input_file.results[category].to_netcdf(spill_path, group=category, mode='a')

    input_file.results = fm.SpilledResults(spill_path, categories)
    return input_file


def compile_results(dict_len, simulator='crunchtope'):
    """Compile results from distributed runs.

    A run can fail in two ways: it can return nothing at all (no pickle to read, e.g. the worker
    was killed), or it can come back carrying a non-zero ``error_code`` set by the simulator wrapper
    (a timeout, a convergence failure, a missing input file). Only runs that returned cleanly hold
    results worth compiling, so the others are counted, reported and left out of the results file.

    Each run's results are spilled to a temporary netCDF file as its pickle is read, rather than
    every run's output being held in memory at once. results.nc is grouped by output category while
    the pickles are per run, so writing it means transposing the two; spilling bounds that to one run
    plus the single category being written.

    Measured on a synthetic sweep of 24 runs carrying 461 MB of arrays across 6 categories, peak RSS
    falls from 748 MB to 491 MB, and the growth with total data from ~1.2 to ~0.37 MB per MB — the
    remaining slope being one category across all runs, which is irreducible while xarray does the
    concatenation. In exchange the results are written to disk twice, which cost 0.8 s against 3.5 s
    on that sweep: immaterial beside the simulations themselves, but it does mean transient use of
    the temporary directory. Point TMPDIR at scratch space if the default is small or quota'd.

    Args:
        dict_len: Number of input files that were run
        simulator: Backend that produced the results ('crunchtope', 'pflotran',
            or 'min3p'). Selects the ``dataset_to_netcdf`` behaviour.

    Returns:
        dict: Summary of the run with keys 'total', 'compiled', 'no_output' (list of run numbers
        that returned nothing), 'errors' ({run number: error code} for runs that failed) and
        'results' (the Path written, or None if nothing was). A second sweep in the same directory
        writes results1.nc rather than overwriting, so callers that need to name anything alongside
        the results should take the suffix from that path.
    """
    import shutil
    import tempfile

    from core import file_methods as fm

    no_output = []
    errors = {}
    results_dict = {}
    spill_dir = tempfile.mkdtemp(prefix='omphalos_spill_')

    try:
        for i in range(dict_len):
            try:
                input_file = fm.unpickle(f'run{i}/input_file{i}_complete.pkl')
            except Exception:
                no_output.append(i)
                continue

            error_code = getattr(input_file, 'error_code', 0)
            if error_code:
                errors[i] = error_code
                continue

            results_dict[i] = _spill_results(input_file, i, spill_dir)

        results_path = None
        if results_dict:
            results_path = fm.dataset_to_netcdf(results_dict, simulator=simulator)
            for file in results_dict:
                del results_dict[file].results
        else:
            print('WARNING: no run returned usable output, so no results file was written.')
    finally:
        shutil.rmtree(spill_dir, ignore_errors=True)

    print(f'Files compiled: {len(results_dict)} of {dict_len}.')
    if no_output:
        print(f'Files that returned no output ({len(no_output)}): {no_output}')
    if errors:
        print(f'Files that failed during the run ({len(errors)}), as run: error_code: {errors}')

    return {'total': dict_len, 'compiled': len(results_dict), 'no_output': no_output,
            'errors': errors, 'results': results_path}


def clear_run_directories(num_runs, directory=None):
    """Empty the run directories this sweep will use, and refuse to reuse a bigger sweep's.

    prep_directories.sh does `mkdir run$N` and used to clear nothing, so a directory reused by a
    later sweep kept everything the previous one left: its database, its deck, its .tec output and
    its .rst restart. CrunchTope writes output per snapshot, so a run that produced fewer
    snapshots this time left the extra ones behind to be parsed as its own.

    **The per-run pickle is kept.** It is the record of what ran, which coeus reads, and a rerun
    should not destroy it before there has been a chance to compile it.

    Surplus directories -- run3 to run7 left by an eight-run sweep when this one has three -- are
    refused rather than cleared or ignored. Clearing them would throw away a record; ignoring them
    lets coeus find their pickles and write eight runs' parameters beside three runs' results,
    joined silently on run number. Neither is acceptable without being asked.
    """
    directory = Path(directory) if directory is not None else Path.cwd()
    pattern = re.compile(r'^run(\d+)$')

    existing = {}
    for path in directory.iterdir():
        match = pattern.match(path.name) if path.is_dir() else None
        if match:
            existing[int(match.group(1))] = path

    surplus = sorted(number for number in existing if number >= num_runs)

    if surplus:
        sys.exit(
            f'ERROR: {len(surplus)} run directory(ies) are left over from a larger sweep in this '
            f'directory: {[existing[number].name for number in surplus]}. This sweep has '
            f'{num_runs} run(s), so those would not be rerun, and their pickles would be '
            f'compiled beside this sweep\'s results as if they belonged to it. Move or delete '
            f'them, or run this sweep somewhere else.'
        )

    cleared = 0
    for number in sorted(existing):
        for path in existing[number].iterdir():
            if path.name == f'input_file{number}_complete.pkl':
                continue
            shutil.rmtree(path) if path.is_dir() else path.unlink()
            cleared += 1

    if cleared:
        print(f'Cleared {cleared} file(s) from {len(existing)} reused run directory(ies); '
              f'per-run pickles kept.')
