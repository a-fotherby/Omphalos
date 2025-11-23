"""Methods to handle invoking CrunchTope on an InputFile object."""

from pathlib import Path


def run_dataset(file_dict, tmp_dir, timeout):
    """Run all input files in the dataset.

    Args:
        file_dict: Dictionary of InputFile objects
        tmp_dir: Temporary directory for output files
        timeout: Timeout in seconds for each simulation

    Returns:
        Updated file_dict with results
    """
    for file_num, entry in enumerate(file_dict):
        file_dict[entry] = input_file(file_dict[entry], file_num, tmp_dir, timeout)

    return file_dict


def input_file(input_file, file_num, tmp_dir, timeout):
    """Run a single input file through CrunchTope.

    Args:
        input_file: InputFile object to run
        file_num: File number for logging
        tmp_dir: Temporary directory for output
        timeout: Timeout in seconds

    Returns:
        Updated InputFile with results
    """
    # Convert tmp_dir to Path and resolve to absolute path
    tmp_path = Path(tmp_dir).resolve()

    # Set the input file path
    input_file.path = tmp_path / input_file.path
    input_file.print()

    if input_file.later_inputs:
        for name in input_file.later_inputs:
            input_file.later_inputs[name].path = tmp_path / input_file.later_inputs[name].path
            input_file.later_inputs[name].print()

    if input_file.aqueous_database:
        kinetic_db = input_file.keyword_blocks['RUNTIME'].contents['kinetic_database'][0]
        input_file.aqueous_database.print(str(tmp_path / kinetic_db))

    if input_file.catabolic_pathways:
        input_file.catabolic_pathways.print(str(tmp_path / 'CatabolicPathways.in'))

    crunchtope(input_file, file_num, timeout, tmp_path)

    return input_file


def crunchtope(input_file, file_num, timeout, tmp_dir):
    """Execute CrunchTope on an input file.

    Args:
        input_file: InputFile object to run
        file_num: File number for logging
        timeout: Timeout in seconds
        tmp_dir: Working directory (Path object)
    """
    import sys
    import pexpect as pexp
    from omphalos.settings import crunch_dir

    command = f'{crunch_dir} {input_file.path}'
    process = pexp.spawn(command, timeout=timeout, cwd=str(tmp_dir), encoding='utf-8')
    process.logfile = sys.stdout

    errors = ['EXCEEDED MAXIMUM ITERATIONS', 'TRY A', 'divide by zero', 'NaN']

    error_code = process.expect([pexp.EOF, pexp.TIMEOUT, errors[0], errors[1], errors[2], errors[3]])

    if error_code == 0:
        # Successful run.
        # Make a results object that is an attribute of the InputFile object.
        input_file.get_results(str(tmp_dir))
        print(f'File {file_num} outputs recorded.')

    else:
        # File threw an error.
        print(f'Error {error_code} encountered.')
        input_file.error_code = error_code

    print(f'File {file_num} complete.')

    return input_file


def clean_dir(tmp_dir, file_name):
    """Clean up temporary files from a directory.

    Args:
        tmp_dir: Directory to clean
        file_name: Specific file to remove
    """
    import subprocess
    tmp_path = Path(tmp_dir)
    subprocess.run(['rm', "*.tec"], cwd=str(tmp_path))
    subprocess.run(['rm', "*.out"], cwd=str(tmp_path))
    subprocess.run(['rm', file_name], cwd=str(tmp_path))
