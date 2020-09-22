"""Functions to generate label DataFrames."""
import pandas as pd
import numpy as np
import spatial_constructor as sc


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
    final_vols = raw_labels(data_set, 'volume')
        
    # Create a new DataFrame with the same geometry as the labels by making a deep copy of the coordinate data.
    initial_vols = pd.DataFrame()
    initial_vols = final_vols[['X', 'Y', 'Z']].copy() 
    
    secondary_precip = pd.DataFrame()
    mineral_vol_init = pd.DataFrame()
    # Ensure that all the condition blocks have been sorted.
    for file in data_set:
        
        output_vols = sc.populate_array(data_set[file], primary_species=False)

            
        initial_vol_df = pd.DataFrame(output_vols)
        # Can use any arbitrary dict entry for index here because all key lists for names will be the same.
        initial_vol_df.columns = data_set[file].condition_blocks[next(iter(data_set[file].condition_blocks))].minerals.keys()
        initial_vols = initial_vols.reindex_like(final_vols)
        initial_vols.loc[file].update(initial_vol_df)

    secondary_precip = initial_vols - final_vols
    # Recapture coordinate values, as they are destroyed by subtraction.
    # Somewhat easier to code than indexing the right columns for subtraction.
    # Could be a source of issues but I doubt it.
    secondary_precip[['X', 'Y', 'Z']]= final_vols[['X', 'Y', 'Z']].copy() 

    return secondary_precip