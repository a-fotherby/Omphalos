import numpy as np
import matplotlib as pyplot

"""Return a dictionary of lines in a file, with the values as the line numbers."""
def importFile(filePath):
    inputFile = {}

    with open(filePath, 'r') as f:
        for lineNum, line in enumerate(f):
            # Crunchfiles edited on UNIX systems have newline characters that must be stripped.
            # Also strip any trailing whitespace.
            if line.startswith('!'):
                # It's a commented line, so don't import.
                pass
            else:  
                inputFile.update({lineNum: line.rstrip('\n ')})
        f.close
    return inputFile

"""Search for dictionary keys by value. Numeric keys only, returns numpy array of matches."""
def searchKeysByVal(dict, byVal):
    keysList = np.empty(0, dtype=int)
    itemsList = dict.items()
    for item in itemsList:
        if item[1] == byVal:
            keysList = np.append(keysList, item[0])
    return keysList