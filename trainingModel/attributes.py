"""Functions for generating DataFrames of attributes."""
import pandas as pd
import copy


def get_condition(
        data_set,
        condition,
        species_concs=False,
        mineral_volumes=False,
        mineral_rates=False):
    """Takes a data set (a set of InputFile objects), a condition, and a target label and returns two dataframes; labels and attributes.

    The attribute array will be of dimension (# of InputFile objects x # of primary species).
    """
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
    
    attribute_dfs[0] = normalise_by_frac(attribute_dfs[0])
    attribute_dfs[1] = normalise_by_frac(attribute_dfs[1])
        
    for df in attribute_dfs:
        attributes = attributes.join(df, how='outer')

    return attributes


def mineral_volume(input_file, condition):
    # Creat a deep copy of the mineral volume fraction dictionary so that the
    # data wrangling doesn't mangle the InputFile.
    minerals_dict = copy.deepcopy(
        input_file.condition_blocks[condition].minerals)
    for mineral in minerals_dict:
        minerals_dict[mineral] = [minerals_dict[mineral][0]]

    mineral_df_row = pd.DataFrame.from_dict(minerals_dict, dtype='float')

    return mineral_df_row


def primary_species(input_file, condition):
    primary_species_df_row = pd.DataFrame.from_dict(
        input_file.condition_blocks[condition].primary_species)

    return primary_species_df_row

def normalise_by_frac(attribute_df):
    """Normalise by fraction of sum of components in condition.
    
    For example, if it is species concentrations, express each initial species concentration as a fraction of the total molar concentration in solution.
    
    Arguments:
    
    attribute_df -- The DataFrame of attributes to normalize.
    """
    attribute_sum = attribute_df.sum(axis=1)
    normed_attr_df = attribute_df.divide(attribute_sum, axis=0)
        
    return normed_attr_df
                                    