"""Methods to handle invoking pflotran on an InputFile object."""


def run_dataset(file_dict, tmp_dir, timeout):
    for file_num, entry in enumerate(file_dict):
        file_dict[entry] = input_file(file_dict[entry], file_num, tmp_dir, timeout)

    return file_dict


def input_file(input_file, file_num, tmp_dir, timeout):
    # Print the file. Run it in CT. Collect the results, and assign to a
    # Results object in the InputFile object.
    from pathlib import Path
    input_file.path = Path.cwd() / tmp_dir / input_file.path.name
    input_file.print()
    if input_file.later_inputs:
        for name in input_file.later_inputs:
            input_file.later_inputs[name].path = Path.cwd() / tmp_dir / f'{name}_{input_file.later_inputs[name].path.name}'
            input_file.later_inputs[name].print()
    

    if input_file.later_inputs != {}:
        for file in input_file.later_inputs:
            pflotran(input_file.later_inputs[file], file_num, timeout, tmp_dir)
        concat_results(input_file)
    else: 
        pflotran(input_file, file_num, timeout, tmp_dir)

    return input_file


def pflotran(input_file, file_num, timeout, tmp_dir):
    import sys
    import subprocess as sp
    from pflotran.settings import pflotran_path

    command = ['mpiexec', '-n', '24', pflotran_path, '-pflotranin', input_file.path]
    sp.run(command)

    # Successful run.
    # Make a results object that is an attribute of the InputFile object.
    input_file.get_results()
    print(f'File {file_num} outputs recorded.')
    print('File {} complete.'.format(file_num))

    return input_file

def concat_results(input_file):
    import xarray as xr
    later_inputs_list = [input_file.later_inputs[name].results for name in input_file.later_inputs]
    results = xr.concat(later_inputs_list, dim='time')
    input_file.results = results
    return input_file


def clean_dir(tmp_dir, file_name):
    import subprocess
    subprocess.run(['rm', "*.h5"], cwd=tmp_dir)
    subprocess.run(['rm', file_name], cwd=tmp_dir)
