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

    for i in data_set:
        # Check the condition blocks have been sorted and if not; sort them.
        data_set[i].check_condition_sort(condition)

        # Get the DataFrames containing attribute info for each condition block
        # part and join them together to make attribute df describing the
        # InputFile.
        row = pd.DataFrame()
        row_parts = []

        if mineral_volumes:
            row_parts.append(mineral_volume(data_set[i], condition))
        else:
            pass
        if species_concs:
            row_parts.append(primary_species(data_set[i], condition))
        else:
            pass

        for df in row_parts:
            row = row.join(df, how='outer')

        # Append the attribute row to the attribute DataFrame and return it.
        attributes = attributes.append(row, ignore_index=True)

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
