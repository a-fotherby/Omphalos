import numpy as np
import matplotlib as pyplot
import input_file as ipf

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
    fileName = '{}{}1.tec'.format(path_to_directory, output)
    with open(file_name) as f:
        f.readline()
        header = f.readline()
        columnHeaders = header.split()
        columnHeaders = columnHeaders[2:]
        for i in columnHeaders:
            columnHeaders[columnHeaders.index(i)] = i.replace('"', '')

        df = pd.read_csv(fileName, sep=' ', skipinitialspace=True, skiprows=[0,1,2], names=columnHeaders)

        return df, columnHeaders