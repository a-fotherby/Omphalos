"""Functions for generating DataFrames of attributes from simulation datasets."""

import copy
import numpy as np
import pandas as pd


def get_condition(
        data_set,
        condition,
        species_concs=False,
        mineral_volumes=False,
        mineral_rates=False):
    """Returns a DataFrame of attributes based on an input file condition.

    Doesn't contain any spatial data, just the concentrations and volume fractions
    of the species in the condition. The attribute array will be of dimension
    (# of InputFile objects x # of primary species).

    Args:
        data_set: Dictionary of InputFile objects
        condition: Name of the condition to extract
        species_concs: Whether to include species concentrations
        mineral_volumes: Whether to include mineral volumes
        mineral_rates: Whether to include mineral rates (unused currently)

    Returns:
        DataFrame containing the requested attributes
    """
    attributes = pd.DataFrame()

    mineral_attrs_list = []
    species_attrs_list = []

    for i in data_set:
        # Check the condition blocks have been sorted and if not; sort them.
        data_set[i].check_condition_sort(condition)

        # Get the DataFrames containing attribute info for each condition block
        # part and join them together to make an attributes df describing the
        # InputFile.
        if mineral_volumes:
            mineral_attrs_list.append(mineral_volume(data_set[i], condition))

        if species_concs:
            species_attrs_list.append(primary_species(data_set[i], condition))

    # Use pd.concat instead of deprecated append
    mineral_attrs = pd.concat(mineral_attrs_list, ignore_index=True) if mineral_attrs_list else pd.DataFrame()
    species_attrs = pd.concat(species_attrs_list, ignore_index=True) if species_attrs_list else pd.DataFrame()

    attribute_dfs = [mineral_attrs, species_attrs]

    for df in attribute_dfs:
        attributes = attributes.join(df, how='outer')

    return attributes


def boundary_condition(dataset, boundary='x_begin', species_concs=True, mineral_vols=False):
    """Returns a DataFrame containing the boundary condition for an input file.

    Can specify whether to return primary species, mineral volumes, or both.
    By default returns primary species only.

    Args:
        dataset: The InputFile dictionary to return the boundary conditions for.
        boundary: The boundary over which to return the condition. Takes the
            CrunchTope boundary specifier keyword as a string.
        species_concs: Whether to return primary species conditions.
        mineral_vols: Whether to return mineral volume fractions.

    Returns:
        DataFrame containing the boundary conditions indexed by file number
    """
    # Find out what condition keyword is indicated by the boundary var. In theory
    # this should be the same in all InputFiles (I haven't implemented changing
    # boundary condition keywords in between files yet). So we only check once,
    # at the beginning. In theory, InputFile 0 could have timed out, so use iter
    # to get first available entry.
    condition = dataset[next(iter(dataset))].keyword_blocks['BOUNDARY_CONDITIONS'].contents[boundary][0]

    boundary_conditions = pd.DataFrame()
    concs_list = []
    vol_fracs_list = []

    for i in dataset:
        # Check the condition blocks have been sorted and if not; sort them.
        dataset[i].check_condition_sort(condition)

        # Get the DataFrames containing attribute info for each condition block
        # part and join them together to make an attributes df describing the
        # InputFile.
        if species_concs:
            concs_list.append(primary_species(dataset[i], condition))

        if mineral_vols:
            vol_fracs_list.append(mineral_volume(dataset[i], condition))

    # Use pd.concat instead of deprecated append
    concs = pd.concat(concs_list) if concs_list else pd.DataFrame()
    vol_fracs = pd.concat(vol_fracs_list) if vol_fracs_list else pd.DataFrame()

    attribute_dfs = [concs, vol_fracs]

    for df in attribute_dfs:
        boundary_conditions = boundary_conditions.join(df, how='outer')

    file_index = pd.Index(dataset.keys())

    boundary_conditions.set_index(file_index, inplace=True)
    return boundary_conditions


def mineral_volume(input_file, condition):
    """Extract mineral volume fractions from a condition block.

    Args:
        input_file: InputFile object to extract from
        condition: Name of the condition

    Returns:
        Single-row DataFrame with mineral volume fractions
    """
    # Create a deep copy of the mineral volume fraction dictionary so that the
    # data wrangling doesn't mangle the InputFile.
    minerals_dict = copy.deepcopy(
        input_file.condition_blocks[condition].minerals)

    for mineral in minerals_dict:
        minerals_dict[mineral] = [minerals_dict[mineral][0]]

    mineral_df_row = pd.DataFrame.from_dict(minerals_dict, dtype='float')

    return mineral_df_row


def primary_species(input_file, condition):
    """Extract primary species concentrations from a condition block.

    Args:
        input_file: InputFile object to extract from
        condition: Name of the condition

    Returns:
        Single-row DataFrame with species concentrations
    """
    species_dict = copy.deepcopy(input_file.condition_blocks[condition].concentrations)

    for entry in species_dict:
        if len(species_dict[entry]) > 1:
            species_dict.update({entry: [float(species_dict[entry][-1])]})

    primary_species_df_row = pd.DataFrame.from_dict(species_dict)
    # convert series to float64, else leave as string
    for i in primary_species_df_row:
        primary_species_df_row[i] = pd.to_numeric(primary_species_df_row[i], errors='ignore')

    return primary_species_df_row


def initial_conditions(dataset, concentrations=True, minerals=False):
    """Returns an attribute DataFrame containing the spatial initial condition.

    Extracts spatial initial conditions for each InputFile in a data set.

    Args:
        dataset: Dictionary of InputFile objects
        concentrations: Whether to include species concentrations
        minerals: Whether to include mineral volumes

    Returns:
        xarray Dataset with initial conditions for all files
    """
    import xarray as xr
    from core import spatial_constructor as sc
    # Import labels from omphalos as it's the primary module
    from omphalos import labels as lbls

    for file in dataset:
        for condition in dataset[file].condition_blocks:
            dataset[file].check_condition_sort(condition)

    # TODO: add pH option for initial condition construction. Currently
    # concentrations does not support the H+ ion because sc.populate_array
    # doesn't support pH directly. Will need to add looking in the parameters
    # dict for pH and adding that to the spatial array either as pH or [H+].

    # Make list of species now so that when we stack the coords to the list
    # format, we have a copy that doesn't include X Y and Z. Initial conditions
    # in CrunchTope can at most be combinations of primary species and minerals.
    # Therefore, we construct the template xarray object accordingly.

    conc_ds = xr.Dataset()
    mins_ds = xr.Dataset()

    nxt = next(iter(dataset))
    c_names = []
    m_names = []

    results_array = np.array([])

    if concentrations:
        conc_ds = lbls.raw(dataset, 'totcon')
        c_names = dataset[nxt].condition_blocks[next(iter(dataset[nxt].condition_blocks))].concentrations.keys()
    if minerals:
        mins_ds = lbls.raw(dataset, 'volume')
        m_names = dataset[nxt].condition_blocks[next(iter(dataset[nxt].condition_blocks))].minerals.keys()

    template_arr = xr.merge((conc_ds, mins_ds))

    var_list = list(c_names) + list(m_names)

    # Unstack the template array to make it compatible with data out of the sc.
    # Template array is typically some lbls.raw call of the same type. Data vars
    # must match those that are being constructed.
    template_arr = template_arr.stack(index=('X', 'Y', 'Z'))
    template_arr = template_arr.reset_index(('X', 'Y', 'Z'))
    template_arr = template_arr.reset_coords(('X', 'Y', 'Z'))

    # For each file in the dataset, generate the spatial array describing the
    # initial condition in the long format.
    for i, file in enumerate(dataset):
        update_array = sc.populate_array(dataset[file], concentrations, minerals)
        # If it is the first time, get the shape of the array that will contain
        # the initial condition for each file in the dataset (i.e.
        # (no. of files) x (no. of species) x (no. of grid cells). Initialize that array.
        if i == 0:
            shape = tuple((len(dataset), np.shape(update_array)[0], np.shape(update_array)[1]))
            results_array = np.empty(shape)
        # Add the file initial condition array to the large array for all files.
        # Repeat until all have been added.
        results_array[i, :, :] = update_array

    # To construct the xarray object, we have to pass it a correctly structured
    # dictionary. We construct this now. For every species/variable in the
    # template we create an entry in that name, slicing along the correct axis
    # of results_array.
    results_dict = {var: results_array[:, :, i] for i, var in enumerate(var_list)}
    # Turn each entry into a list, containing the var data, as well the names
    # index and file_num which will become xarray coordinates, in accordance
    # with the xr.ds constructor method.
    for var in results_dict:
        results_dict.update({var: (['file_num', 'index'], results_dict[var])})
    ds = xr.Dataset(results_dict)
    # Unstack the coordinate system again.
    ds = ds.assign({var: template_arr[var] for var in ('X', 'Y', 'Z')})
    ds = ds.set_index(index=('X', 'Y', 'Z'))
    ds = ds.unstack('index')

    return ds


def mineral_rates(dataset):
    """Returns DataFrame of mineral rates indexed by file.

    Args:
        dataset: Dictionary of InputFile objects

    Returns:
        DataFrame with mineral rates for each file
    """
    rate_rows = []
    for i in dataset:
        input_rates = copy.deepcopy(dataset[i].keyword_blocks['MINERALS'].contents)
        rate_dict = {}
        for entry in input_rates:
            for j in input_rates[entry]:
                try:
                    rate = float(j)
                    rate_dict.update({entry: [rate]})
                except ValueError:
                    pass
        rate_rows.append(pd.DataFrame.from_dict(rate_dict, dtype='float'))

    rate_df = pd.concat(rate_rows, ignore_index=True) if rate_rows else pd.DataFrame()

    file_index = pd.Index(dataset.keys())
    rate_df.set_index(file_index, inplace=True)

    return rate_df


def aqueous_rates(dataset):
    """Returns DataFrame of aqueous rates indexed by file.

    Args:
        dataset: Dictionary of InputFile objects

    Returns:
        DataFrame with aqueous rates for each file
    """
    rate_rows = []
    for i in dataset:
        input_rates = copy.deepcopy(dataset[i].keyword_blocks['AQUEOUS_KINETICS'].contents)
        rate_dict = {}
        for entry in input_rates:
            if entry == 'AQUEOUS_KINETICS':
                continue
            rate_dict.update({entry: [float(input_rates[entry][-1])]})

        rate_rows.append(pd.DataFrame.from_dict(rate_dict, dtype='float'))

    rate_df = pd.concat(rate_rows, ignore_index=True) if rate_rows else pd.DataFrame()

    file_index = pd.Index(dataset.keys())
    rate_df.set_index(file_index, inplace=True)

    return rate_df


def normalise_by_frac(attribute_df):
    """Normalise by fraction of sum of components in condition.

    For example, if it is species concentrations, express each initial species
    concentration as a fraction of the total molar concentration in solution.

    Args:
        attribute_df: The DataFrame of attributes to normalise.

    Returns:
        DataFrame with normalised values
    """
    attribute_sum = attribute_df.sum(axis=1)
    normed_attr_df = attribute_df.divide(attribute_sum, axis=0)

    return normed_attr_df
