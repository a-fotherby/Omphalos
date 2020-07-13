import numpy as np
import matplotlib as pyplot
import inputFile as ipf


def importFile(filePath):
    """Return a dictionary of lines in a file, with the values as the line numbers.

    Will ignore any commented lines in the CT input file, but will still count their line number,
    so line numbers in dictionary will map to the true line number in the file.
    """
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


def searchInputFile(dict, byVal):
    """Search for CT input file line nums by string. Returns a numpy array of matching line numbers.

    Will search for partial matches at the beginning of the line -
    e.g. if you wanted to find all the CONDITION keywords by you didn't know the name of each keyword block
    you could search by using 'CONDITON'.
    You can't search from the back, however, so can't find a specific CONDITION block line num by searching for its name.
    """
    keysList = np.empty(0, dtype=int)
    itemsList = dict.items()
    for item in itemsList:
        if item[1].startswith(byVal):
            keysList = np.append(keysList, item[0])
    return keysList
