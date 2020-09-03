"""Functions to generate label DataFrames."""
import pandas as pd


def raw_labels(data_set, output):
    """Returns labels DataFrame containing raw CrunchTope output data.
    
    Will return a multi-indexed DataFrame, the level=1 index is the file number, and the level=0 index is a simple row count.
    Spatial data for each input file is stored in a tidy format (tidy taking it's technical meaning in this case).
    """
    # Generate dataframe of requested labels.
    labels = pd.DataFrame()
    for key in data_set:
        data_set[key].results.results_dict[output]['File Num'] = key
        labels = labels.append(data_set[key].results.results_dict[output])
    
    labels = labels.set_index(['File Num', labels.index])

    return labels


def secondary_precip(data_set):
    """Calculate the total mineral volume evolution over the run by comparing the initial conditions to the final mineral volume output.

    Keyword arguments:
    data_set -- The data set to calculate the secondary preciptation for.
    """
    
    # Get DataFrame of output volumes.
    final_vols = lbls.raw_labels(data_set, 'volume')
        
    # Create a new DataFrame with the same geometry as the labels by making a deep copy of the coordinate data.
    initial_vols = pd.DataFrame()
    initial_vols = final_vols[['X', 'Y', 'Z']].copy() 
    
    secondary_precip = pd.DataFrame()
    mineral_vol_init = pd.DataFrame()
    # Ensure that all the condition blocks have been sorted.
    for i, file in enumerate(data_set):
        
        # Initialise discretization array as CrunchTope defaults.
        # Could probably move this to be the default when input files are being read in/generated but will leave here for now.
        disc = [[1, 1], [1, 1], [1,1]]
        
        try:
            # We ensure discretization data is read in as floats.
            disc[0] = [float(i) for i in test_set[0].keyword_blocks['DISCRETIZATION'].contents['xzones']]
            disc[1] = [float(i) for i in test_set[0].keyword_blocks['DISCRETIZATION'].contents['yzones']]
            disc[2] = [float(i) for i in test_set[0].keyword_blocks['DISCRETIZATION'].contents['zzones']]
        except KeyError as error:
            print("The discretization in {} has not been specified.\nIf this is in error, check your input file.".format(error.args[0]))
            
        row_count = int(disc[0][0] * disc[1][0] * disc[2][0])
            
        # Initialise output volume np.array and get the condition volume fractions.

        output_vols = np.zeros((row_count, len(data_set[file].keyword_blocks['MINERALS'].contents) - 1))    
        
        # Construct an initial volume fraction field using initial conditions and the region attribute.
        for condition in data_set[file].condition_blocks:
            print(condition)
            data_set[file].check_condition_sort(condition)

            # Get list of all minerals in the system and record the starting volume
            # fraction for each.
            mineral_dict = {}

            for key in data_set[file].condition_blocks[condition].minerals:
                mineral_dict.update({key: data_set[file].condition_blocks[condition].minerals[key][0]})


            # Now initialise np.array() based on geometry of system contained in discretization info.
            # CT cycles through coordinates x -> y -> z in TecPlot output format so we need an array with xboxes * yboxes * zboxes number of rows and minerals number of columns.

            # Following on from this, any coord has a row number = [x + (y * x_len) + (z * x_len * y_len)] in this scheme. (Where coord counting starts from (0, 0, 0))
            # Contiguous areas in real space are not necissarily contiguous in the row format.


            condition_vols = np.fromiter(mineral_dict.values(), dtype=float)

            # Need to get row numbers for each condition and each region specified to start with that condition.
            # (Still need to amend file reading so that it can correctly interperate non-contiguous condition regions)
            # Recall that range_set refers to block numbers not coordinates and that counting starts from 1, so must be adjusted at start, but not the end becuase np.arange doesn't include the final number.
            # Lots of fence-post errors to keep track of here.
            
            range_set_list = data_set[file].condition_blocks[condition].region

            for range_set in range_set_list:

                print(range_set)

                if range_set == [[0,0], [0,0], [0,0]]:
                    print("Unused condition '{}' detected. Skipping.".format(condition))
                    pass
                else:
                    x_rows = np.arange((range_set[0][0]-1), range_set[0][1])
                    y_rows = np.arange((range_set[1][0]-1), range_set[1][1])
                    z_rows = np.arange((range_set[2][0]-1), range_set[2][1])

                    index_list_len = len(x_rows) * len(y_rows) * len(z_rows)
                    print(index_list_len)
                    row_list = [0] * index_list_len

                    # Get a list of the row indicies corresponding to the region where the condition is applied.
                    n = 0
                    for z in z_rows:
                        for y in y_rows:
                            for x in x_rows:
                                row_list[n] = int(x + (y * len(x_rows)) + (z * len(y_rows) * len(z_rows)))
                                n = n + 1

                    print(row_list)
                    for row in row_list:
                        output_vols[row] = condition_vols
            
        initial_vol_df = pd.DataFrame(output_vols)
        initial_vol_df.columns = mineral_dict.keys()
        initial_vols = initial_vols.reindex_like(final_vols)
        initial_vols.loc[file].update(initial_vol_df)
    
    
    display(initial_vols)
    display(final_vols)
    secondary_precip = initial_vols - final_vols
    # Recapture coordinate values, as they are destroyed by subtraction.
    # Somewhat easiers to code than indexing the right columns for subtraction.
    # Could be a source of issues but I doubt it.
    secondary_precip[['X', 'Y', 'Z']]= final_vols[['X', 'Y', 'Z']].copy() 

    return secondary_precip