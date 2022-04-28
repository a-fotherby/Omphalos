"""Methods for constructing tidy DataFrames of CrunchTope data.

We have to go through this roundabout method because it's the easiest way to construct spatial arrays when then are
multiple connected (potentially discontinuous) zones in the initial condition, rather than directly trying to make the
xarray object.
"""


def populate_array(input_file, primary_species=True, mineral_vols=False):
    """Populates an empty initial condition spatial array with species and mineral data.
    
    Arguments:
    array --  the empty array generated by initialise_array() to populate.
    input_file --  the input file containing the data for population.
    """
    import numpy as np

    # Construct an initial volume fraction field using initial conditions and the region attribute.
    for condition in input_file.condition_blocks:
        input_file.check_condition_sort(condition)

        primary_species_dict = {}
        mineral_dict = {}

        if primary_species:
            # Have to iterate and update dict to stop values being read as single element arrays.
            for key in input_file.condition_blocks[condition].concentrations:
                primary_species_dict.update({key: input_file.condition_blocks[condition].concentrations[key][0]})

        if mineral_vols:
            # Get list of all minerals in the system and record the starting volume fraction for each. 
            # Populate a new mineral dict because the condition block entry contains surface area info.
            for key in input_file.condition_blocks[condition].minerals:
                mineral_dict.update({key: input_file.condition_blocks[condition].minerals[key][0]})

        condition_dict = {**primary_species_dict, **mineral_dict}

        # Convert values stored as strings in InputFile to floats.
        # If it's a string that can't be converted, e.g. 'charge', then set to nan.
        for i in condition_dict:
            try:
                condition_dict[i] = float(condition_dict[i])
            except:
                condition_dict[i] = np.nan

        initial_condition = np.fromiter(condition_dict.values(), dtype=float, count=len(condition_dict))

        array = initialise_array(input_file, len(initial_condition))

        row_list = compute_rows(input_file, condition)

        for row in row_list:
            array[row] = initial_condition

        return array


def initialise_array(input_file, variable_num, verbose=False):
    import numpy as np
    """Returns the empty numpy array representing the coordinate grid.
    
    CT cycles through coordinates x -> y -> z in TecPlot output format so we need an array with xboxes * yboxes * 
    zboxes number of rows and species number of columns. Following on from this, any coord has a row number = [x + (y 
    * x_len) + (z * x_len * y_len)] in this scheme. (Where coord counting starts from (0, 0, 0)) Contiguous areas in 
    real space are not necessarily contiguous in the row format. 
    
    Arguments:
    input_file -- InputFile object to construct the array for.
    variable_num -- The number of variables (species, minerals) to be recorded in the array.
    """
    # Initialise discretization array as CrunchTope defaults. Could probably move this to be the default when input
    # files are being read in/generated but will leave here for now. If I did move it to the file reading routine,
    # we would need another emthod just for discretization (or maybe a function decorator of some sort). At any rate,
    # it's easier to leave it here for now.
    disc = [[1, 1], [1, 1], [1, 1]]

    zone_list = ['xzones', 'yzones', 'zzones']

    try:
        for i, zone in enumerate(zone_list):
            # We ensure discretization data is read in as floats.
            disc[i] = [float(j) for j in input_file.keyword_blocks['DISCRETIZATION'].contents[zone]]
    except KeyError as error:
        if verbose == True:
            print(
                "The discretization in {} has not been specified.\nIf this is in error, check your input "
                "file.\nOtherwise, update your input file to suppress this error.".format(
                    error.args[0]))
        else:
            pass
    # Get the total number of rows required by the tidy data format for this geometry.    
    row_count = int(disc[0][0] * disc[1][0] * disc[2][0])

    # Initialise output volume np.array and get the condition volume fractions.    
    array = np.zeros((row_count, variable_num))

    return array


def compute_rows(input_file, condition):
    """Compute the list of row numbers that correspond to the regions over which the condition is specified.
    
    Returns: row_list -- a list of integers specifying which rows in the initial state array correspond (in the tidy
    format) to the region for the initial condition.
    """
    import numpy as np

    # Any coord has a row number = [x + (y * x_len) + (z * x_len * y_len)] in this scheme. (Where coord counting
    # starts from (0, 0, 0)) Contiguous areas in real space are not necessarily contiguous in the row format. Need to
    # get row numbers for each condition and each region specified to start with that condition.

    condition_regions = input_file.condition_blocks[condition].region

    for region in condition_regions:

        if region == [[0, 0], [0, 0], [0, 0]]:
            print("Unused condition '{}' detected.".format(condition))
            pass
        else:
            # Recall that region refers to block numbers not coordinates and that counting starts from 1, so must be
            # adjusted at start, but not the end becuase np.arange doesn't include the final number. Lots of
            # fence-post errors to keep track of here. There is definately a smart way to do the next 13 lines of
            # code with iterables and clever array. I really cba and also we're never going above 3D so there isn't
            # much point because this is much more readable. Maybe I'll get around to it one day...
            x_rows = np.arange((region[0][0] - 1), region[0][1])
            y_rows = np.arange((region[1][0] - 1), region[1][1])
            z_rows = np.arange((region[2][0] - 1), region[2][1])

            row_list_len = len(x_rows) * len(y_rows) * len(z_rows)
            # Make a list of zeros the length of row_list_len. NOT a numpy array.
            row_list = [0] * row_list_len

            # Get a list of the row indicies corresponding to the region where the condition is applied.
            n = 0
            for z in z_rows:
                for y in y_rows:
                    for x in x_rows:
                        row_list[n] = int(x + (y * len(x_rows)) + (z * len(y_rows) * len(z_rows)))
                        n = n + 1
            return row_list
