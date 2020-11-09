import numpy as np
import matplotlib as pyplot
import pandas as pd
import re
import copy
import os
import glob
import pickle


def import_file(file_path):
    """Return a dictionary of lines in a file, with the values as the line numbers.

    Will ignore any commented lines in the CT input file, but will still count their line number,
    so line numbers in dictionary will map to the true line number in the file.
    """
    input_file = {}

    with open(file_path, 'r') as f:
        for line_num, line in enumerate(f):
            # Crunchfiles edited on UNIX systems have newline characters that must be stripped.
            # Also strip any trailing whitespace.
            if line.startswith('!'):
                # It's a commented line, so don't import.
                pass
            else:
                input_file.update({line_num: line.rstrip('\n ')})
        f.close
    return input_file


def search_input_file(dict, by_val):
    """Search for CT input file line nums by string. Returns a numpy array of matching line numbers.

    Will search for partial matches at the beginning of the line -
    e.g. if you wanted to find all the CONDITION keywords by you didn't know the name of each keyword block
    you could search by using 'CONDITON'.
    You can't search from the back, however, so can't find a specific CONDITION block line num by searching for its name.
    """
    keys_list = np.empty(0, dtype=int)
    items_list = dict.items()
    for item in items_list:
        if item[1].startswith(by_val):
            keys_list = np.append(keys_list, item[0])
    return keys_list


def read_tec_file(path_to_directory, output):
    """Import the spatial profile output file of the system at the target time specified in the input file. Takes files in the tecplot format."""
    file_name = '{}{}1.tec'.format(path_to_directory, output)
    # Column headers are quite badly mangled by tecplot output format. Python csv sniffer will not correctly identify the column headers.
    # So we manually create the correct list by opening the file and navigating to the second line (the header line for tecplot outputs)
    # and perform some judicious stripping and a regex split to generate the correct list of column headers.
    # We can then pass the header list straight to the read_table method as an
    # override.
    with open(file_name) as f:
        f.readline()
        headers = f.readline()
        headers = headers.strip('VARIABLES = "')
        headers = headers.rstrip('" \n')
        headers = re.split(r'"\s+"', headers)

        df = pd.read_table(
            file_name,
            mangle_dupe_cols=True,
            sep=r'\s+',
            skipinitialspace=True,
            skiprows=[
                0,
                1,
                2],
            names=headers)

        return df


def get_data_cats(directory):
    # os.chdir(directory)
    f_list = glob.glob(directory + '*.tec')
    f_list = [i.rstrip('.tec') for i in f_list]
    f_list = [i.rstrip('0123456789') for i in f_list]
    f_list = [i.split('/', 1)[-1] for i in f_list]
    f_set = set(f_list)
    return f_set


def pickle_data_set(data_set, file_name):
    with open('{}.pickle'.format(file_name), 'wb') as f:
        # Pickle the 'data' dictionary using the highest protocol available.
        pickle.dump(data_set, f, pickle.HIGHEST_PROTOCOL)


def unpickle(file_name):
    with open(file_name, 'rb') as f:
        # The protocol version used is detected automatically, so we do not
        # have to specify it.
        data = pickle.load(f)
        return data
