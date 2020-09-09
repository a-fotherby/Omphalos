"""Methods for constructing tidy DataFrames of CrunchTope data."""


def initialise_array(input_file, variable_num):
    import numpy as np
    """Returns the empty numpy array representing the coordinate grid.
    
    Arguments:
    input_file -- InputFile object to construct the array for.
    variable_num -- The number of variables (species, minerals) to be recorded in the array.
    """
    # Initialise discretization array as CrunchTope defaults.
    # Could probably move this to be the default when input files are being read in/generated but will leave here for now.
    # If I did move it to the file reading routine, we would need another emthod just for discretization (or maybe a function decorator of some sort).
    # At any rate, it's easier to leave it here for now.
    disc = [[1, 1], [1, 1], [1,1]]

    zone_list = ['xzones', 'yzones', 'zzones']
    
    try:
        for i, zone in enumerate(zone_list):
            # We ensure discretization data is read in as floats.
            disc[i] = [float(j) for j in input_file.keyword_blocks['DISCRETIZATION'].contents[zone]]
            #disc[1] = [float(i) for i in data_set[file].keyword_blocks['DISCRETIZATION'].contents['yzones']]
            #disc[2] = [float(i) for i in data_set[file].keyword_blocks['DISCRETIZATION'].contents['zzones']]
    except KeyError as error:
        print("The discretization in {} has not been specified.\nIf this is in error, check your input file.\nOtherwise, update your input file to suppress this error.".format(error.args[0]))

    # Get the total number of rows required by the tidy data format for this geometry.    
    row_count = int(disc[0][0] * disc[1][0] * disc[2][0])

    # Initialise output volume np.array and get the condition volume fractions.    
    array = np.zeros((row_count, variable_num))
    
    return array