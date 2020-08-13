"""Functions to generate label DataFrames."""
import pandas as pd

def raw_labels(data_set, output):
    """Returns labels DataFrame containing raw CrunchTope output data."""
    # Generate dataframe of requested labels.
    labels = pd.DataFrame()
    label_names = data_set[0].results.results_dict[output]
    for label in label_names:
        label_list = pd.DataFrame()
        for i in data_set:
            label_list = label_list.append(data_set[i].results.results_dict[output][label], ignore_index = True)
            
        label_list.columns = [label]
        labels[label] = label_list[label]

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
    
        # Get list of all minerals in the system and record the starting volume fraction for each.
        mineral_dict = data_set[file].condition_blocks[condition].minerals
        for key in mineral_dict:
            mineral_dict.update({key: mineral_dict[key][0]})
        
        file_volumes = pd.DataFrame(mineral_dict, index=[i], dtype = float)
        mineral_vol_init = mineral_vol_init.append(file_volumes)

    mineral_vol_out = raw_labels(data_set, 'volume')
    secondary_precip = mineral_vol_init - mineral_vol_out
    return secondary_precip
