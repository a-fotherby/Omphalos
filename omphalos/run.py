"""Methods to handle invoking CrunchTope on an InputFile object."""


def run_dataset(file_dict, tmp_dir, timeout):
    for file_num, entry in enumerate(file_dict):
        file_dict[entry] = input_file(file_dict[entry], file_num, tmp_dir, timeout)

    return file_dict


def input_file(input_file, file_num, tmp_dir, timeout):
    # Print the file. Run it in CT. Collect the results, and assign to a
    # Results object in the InputFile object.

    name = 'input_file'
    file_name = name + str(file_num) + '.in'
    input_file.path = tmp_dir + file_name
    input_file.print()
    if input_file.aqueous_database:
        input_file.aqueous_database.print(
            tmp_dir + input_file.keyword_blocks['RUNTIME'].contents['kinetic_database'][0])
    if input_file.catabolic_pathways:
        input_file.catabolic_pathways.print(tmp_dir + 'CatabolicPathways.in')

    crunchtope(input_file, file_name, file_num, timeout, tmp_dir)

    return input_file


def crunchtope(input_file, file_name, file_num, timeout, tmp_dir):
    import sys
    import pexpect as pexp
    from omphalos.settings import crunch_dir

    command = f'{crunch_dir} {file_name}'
    process = pexp.spawn(command, timeout=timeout, cwd=tmp_dir, encoding='utf-8')
    process.logfile = sys.stdout

    errors = ['EXCEEDED MAXIMUM ITERATIONS', 'TRY A', 'nrerror: singular matrix']

    error_code = process.expect([pexp.EOF, pexp.TIMEOUT, errors[0], errors[1], errors[2]])

    if error_code == 0:
        # Successful run.
        # Make a results object that is an attribute of the InputFile object.
        input_file.get_results(tmp_dir)
        print(f'File {file_num} outputs recorded.')
        clean_dir(tmp_dir, file_name)

    else:
        # File threw an error.
        print(f'Error {error_code} encountered.')
        input_file.error_code = error_code
        # Clean the temp directory ready the next input file.
        clean_dir(tmp_dir, file_name)

    print('File {} complete.'.format(file_num))

    return input_file


def clean_dir(tmp_dir, file_name):
    import subprocess
    subprocess.run(['rm', "*.tec"], cwd=tmp_dir)
    subprocess.run(['rm', "*.out"], cwd=tmp_dir)
    subprocess.run(['rm', file_name], cwd=tmp_dir)
