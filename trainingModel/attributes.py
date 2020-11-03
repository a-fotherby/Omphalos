"""Functions for generating DataFrames of attributes."""

def get_condition(
        data_set,
        condition,
        species_concs=False,
        mineral_volumes=False,
        mineral_rates=False):
    """Returns a normalised DataFrame of attributes based on an input file condition.
    
    Doesn't contain any spatial data, just the concentrations and volume fractions of the species in the condition.
    The attribute array will be of dimension (# of InputFile objects x # of primary species).
    """
    import pandas as pd
    
    # Put data into a dataframe for visualisation.
    # Currently only supports primary_species but can easily be extended to
    # other attributes of a ConditionBlocks once Omphalos supports their
    # randomisation.
    attributes = pd.DataFrame()

    mineral_attrs = pd.DataFrame()
    species_attrs = pd.DataFrame()
    
    for i in data_set:
        # Check the condition blocks have been sorted and if not; sort them.
        data_set[i].check_condition_sort(condition)

        # Get the DataFrames containing attribute info for each condition block
        # part and join them together to make an attributes df describing the
        # InputFile.
        if mineral_volumes:
            mineral_attrs = mineral_attrs.append(mineral_volume(data_set[i], condition), ignore_index=True)

        else:
            pass
    
        if species_concs:
            species_attrs = species_attrs.append(primary_species(data_set[i], condition), ignore_index=True)
            
        else:
            pass

    attribute_dfs = [mineral_attrs, species_attrs]   
        
    for df in attribute_dfs:
        attributes = attributes.join(df, how='outer')
        
    return attributes

def boundary_condition(data_set, boundary='x_begin', species_concs=True, mineral_vols=False):
    """Returns a DataFrame containing the boundary condition for an input file.
    Can specify whether to return primary species, mineral volumes, or both.
    By default returns primary species only.
    
    Arguments:
    data_set -- The InputFile dictionary to return the boundary conditions for.
    
    Keyword Arguments:
    boundary -- The boundary over which to return the condition. Takes the CrunchTope boundary specifier keyword as a string for an argument.
    primary_species -- Bool. Whether or not to return primary species conditions.
    mineral_vols -- Bool. Whether or not to return mineral volume fractions.
    """
    
    import pandas as pd
    
    # Find out what condition keyword is indicicated by the boundary var.
    # In theory this should be the same in all InputFiles (I haven't implement changing boundary condition keywords in between files yet).
    # So we only check once, at the beginning.
    # In theory, InputFile 0 could have timed out, so use iter to get first available entry.
    condition = data_set[next(iter(data_set))].keyword_blocks['BOUNDARY_CONDITIONS'].contents[boundary][0]
    
    boundary_conditions = pd.DataFrame()
    concs = pd.DataFrame()
    vol_fracs = pd.DataFrame()
    
    for i in data_set:
        # Check the condition blocks have been sorted and if not; sort them.
        data_set[i].check_condition_sort(condition)

        # Get the DataFrames containing attribute info for each condition block
        # part and join them together to make an attributes df describing the
        # InputFile.

        if species_concs:
            concs = concs.append(primary_species(data_set[i], condition), ignore_index=True)

        if mineral_vols:
            vol_fracs = vol_fracs.append(mineral_volume(data_set[i], condition), ignore_index=True)
    
    attribute_dfs = [concs, vol_fracs]   
        
    for df in attribute_dfs:
        boundary_conditions = boundary_conditions.join(df, how='outer')
    
    file_index = pd.Index(data_set.keys())
    
    boundary_conditions.set_index(file_index, inplace=True)
    return boundary_conditions
    

def mineral_volume(input_file, condition):
    """"""
    import pandas as pd
    import copy
    # Creat a deep copy of the mineral volume fraction dictionary so that the
    # data wrangling doesn't mangle the InputFile.
    minerals_dict = copy.deepcopy(
        input_file.condition_blocks[condition].minerals)
    for mineral in minerals_dict:
        minerals_dict[mineral] = [minerals_dict[mineral][0]]

    mineral_df_row = pd.DataFrame.from_dict(minerals_dict, dtype='float')

    return mineral_df_row


def primary_species(input_file, condition):
    import pandas as pd
    primary_species_df_row = pd.DataFrame.from_dict(
        input_file.condition_blocks[condition].primary_species)

    return primary_species_df_row

def initial_conditions(data_set, primary_species=False, mineral_vols=False):
    """Returns an attribute DataFrame containing the spatial initial condition for each InputFile in a data set.
    
    """ 
    import labels as lbls
    import pandas as pd
    import numpy as np
    import spatial_constructor as sc
    
    # Create a new DataFrame with the same geometry as the labels by making a deep copy of the coordinate data.
    # Use totcon because it's always present 
    initial_conditions = lbls.raw_labels(data_set, 'totcon')[['X', 'Y', 'Z']].copy()
    
    secondary_precip = pd.DataFrame()
    mineral_vol_init = pd.DataFrame()
    
    primary_species_dict = {}
    mineral_dict = {}
    
    if primary_species:
        primary_species_dict = data_set[next(iter(data_set))].condition_blocks[next(iter(data_set[next(iter(data_set))].condition_blocks))].primary_species
        
    if mineral_vols:
        mineral_dict = data_set[next(iter(data_set))].condition_blocks[next(iter(data_set[next(iter(data_set))].condition_blocks))].minerals
    
    condition_dict = {**primary_species_dict, **mineral_dict}
    column_names = condition_dict.keys()
    
    initial_conditions[list(column_names)] = np.nan

    for file in data_set:
        condition_array = sc.populate_array(data_set[file])
        condition_df = pd.DataFrame(condition_array)

        condition_df.columns = column_names
        
        initial_conditions.loc[file].update(condition_df)

    return initial_conditions

def normalise_by_frac(attribute_df):
    """Normalise by fraction of sum of components in condition.
    
    For example, if it is species concentrations, express each initial species concentration as a fraction of the total molar concentration in solution.
    
    Arguments:
    
    attribute_df -- The DataFrame of attributes to normalize.
    """
    import pandas as pd
    attribute_sum = attribute_df.sum(axis=1)
    normed_attr_df = attribute_df.divide(attribute_sum, axis=0)
        
    return normed_attr_df
                                    