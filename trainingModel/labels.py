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


def secondary_precip(data_set, condition):
    """Calculate the total mineral volume evolution over the run.

    Currently only able to handle a single, uniform geochemical condition for the entire system.
    Keyword arguments:
    condition -- the dictionary entry key for the condition in question.
    """
    secondary_precip = pd.DataFrame()
    mineral_vol_init = pd.DataFrame()
    # Ensure that all the condition blocks have been sorted.
    for i, file in enumerate(data_set):
        data_set[file].check_condition_sort(condition)

        # Get list of all minerals in the system and record the starting volume
        # fraction for each.
        mineral_dict = data_set[file].condition_blocks[condition].minerals
        for key in mineral_dict:
            mineral_dict.update({key: mineral_dict[key][0]})

        file_volumes = pd.DataFrame(mineral_dict, index=[i], dtype=float)
        mineral_vol_init = mineral_vol_init.append(file_volumes)

    mineral_vol_out = raw_labels(data_set, 'volume')
    secondary_precip = mineral_vol_init - mineral_vol_out
    return secondary_precip
