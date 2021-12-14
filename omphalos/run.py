"""Methods to handle invoking CrunchTope on an InputFile object."""


def run_dataset(file_dict, tmp_dir, timeout):
    for file_num, entry in enumerate(file_dict):
        file_dict[entry] = run_input_file(file_dict[entry], file_num, tmp_dir, timeout)
    # Remove timed-out entries.
    timeout_list = []
    for file in file_dict:
        if file_dict[file].timeout:
            timeout_list.append(file)
    for file_num in timeout_list:
        file_dict.pop(file_num)

    return file_dict


def run_input_file(input_file, file_num, tmp_dir, timeout):
    # Print the file. Run it in CT. Collect the results, and assign to a
    # Results object in the InputFile object.
    import signal
    import subprocess
    import omphalos.results as results
    import omphalos.file_methods as fm

    name = 'input_file'
    file_name = name + str(file_num) + '.in'
    input_file.path = tmp_dir + file_name
    input_file.print_input_file()
    if input_file.aqueous_database:
        input_file.aqueous_database.print(tmp_dir + input_file.keyword_blocks['RUNTIME'].contents['kinetic_database'][0])
    if input_file.catabolic_pathways:
        input_file.catabolic_pathways.print(tmp_dir + 'CatabolicPathways.in')

    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(int(timeout))
    try:
        crunchtope(file_name, tmp_dir)
    except Exception:
        print(f'File {file_num} timed out.')
        input_file.timeout = True
        # Clean the temp directory ready the next input file.
        subprocess.run(['rm', "*.tec"], cwd=tmp_dir)
        subprocess.run(['rm', "*.out"], cwd=tmp_dir)
        # subprocess.run(['rm', file_name], cwd=tmp_dir)
        return input_file

    signal.alarm(0)

    # Make a results object that is an attribute of the InputFile object.
    input_file.results = results.Results()

    output_categories = fm.get_data_cats(tmp_dir)
    for output in output_categories:
        input_file.results.get_output(tmp_dir, output)

    # Clean the temp directory ready the next input file.
    subprocess.run(['rm', '*.tec'], cwd=tmp_dir)
    subprocess.run(['rm', file_name], cwd=tmp_dir)
    subprocess.run(['rm', '*.out'], cwd=tmp_dir)

    print('File {} complete.'.format(file_num))

    return input_file


def crunchtope(file_name, tmp_dir):
    import omphalos.settings as settings
    import subprocess
    # Get CT install directory from settings.py.
    subprocess.run([settings.crunch_dir, file_name], cwd=tmp_dir)


def timeout_handler(signum, frame):
    raise Exception(f"CrunchTimeout")
