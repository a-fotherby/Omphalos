"""Methods for constructing tidy DataFrames of geochemical data.

We have to go through this roundabout method because it's the easiest way to
construct spatial arrays when there are multiple connected (potentially
discontinuous) zones in the initial condition, rather than directly trying
to make the xarray object.
"""

import numpy as np


# The column name used for pH, and the condition block parameter it is read from.
PH_NAME = 'pH'


def _ph_entry(block):
    """Return the pH token a condition block declares, or None if it declares none.

    CrunchTope takes pH as a condition block parameter rather than as an H+ concentration, so
    InputFile.sort_condition_block files it under ConditionBlock.parameters and it never appears
    among the concentrations. The keyword is matched case insensitively because the input file
    parser preserves whatever spelling the file used.
    """
    for name, entry in block.parameters.items():
        if name.lower() == PH_NAME.lower() and entry:
            return entry[0]

    return None


def condition_variables(input_file, primary_species=True, mineral_vols=False, ph=False):
    """Return the ordered variable names that populate_array writes as array columns.

    Names are collected across every condition block, concentrations first, then mineral volumes,
    then pH, in first-seen order. Taking the union means a condition that declares an extra species
    cannot shift the columns belonging to another one. pH is placed last so that turning it on
    leaves the existing columns where they were.

    Callers that label the array must use this same ordering; core.attributes.initial_conditions does.

    Args:
        input_file: The input file to read condition blocks from.
        primary_species: Whether to include primary species concentrations.
        mineral_vols: Whether to include mineral volume fractions.
        ph: Whether to include pH. Contributes a column only if some condition declares pH.

    Returns:
        list of variable names, in column order
    """
    concentration_names = []
    mineral_names = []
    ph_names = []

    for condition in input_file.condition_blocks:
        input_file.check_condition_sort(condition)
        block = input_file.condition_blocks[condition]

        if primary_species:
            for name in block.concentrations:
                if name not in concentration_names:
                    concentration_names.append(name)

        if mineral_vols:
            for name in block.mineral_volumes:
                if name not in mineral_names:
                    mineral_names.append(name)

        if ph and not ph_names and _ph_entry(block) is not None:
            ph_names.append(PH_NAME)

    return concentration_names + mineral_names + ph_names


def _condition_row(input_file, condition, names, primary_species, mineral_vols, ph=False):
    """Build one row of initial values for a condition, ordered to match names.

    Values a condition does not declare, and values that are not numeric (CrunchTope accepts
    'charge', a mineral name, or a gas name in place of a concentration), come back as nan.

    pH is recorded as pH, not converted to an H+ concentration: CrunchTope's pH is -log10 of the H+
    activity, and recovering a concentration from it needs the activity coefficients that only the
    speciation solve produces. Those are not available from the input file, so converting here would
    mean inventing an ideal-solution assumption the model itself does not make.
    """
    block = input_file.condition_blocks[condition]

    values = {}
    if primary_species:
        # Index the first token: the remainder of the entry is a constraint such as 'charge' or an
        # equilibrating gas, not part of the value.
        values.update({name: entry[0] for name, entry in block.concentrations.items()})
    if mineral_vols:
        # The condition block entry also carries surface area info, hence the first token again.
        values.update({name: entry[0] for name, entry in block.mineral_volumes.items()})
    if ph:
        ph_entry = _ph_entry(block)
        if ph_entry is not None:
            values[PH_NAME] = ph_entry

    row = np.full(len(names), np.nan)
    for i, name in enumerate(names):
        if name not in values:
            continue
        try:
            row[i] = float(values[name])
        except ValueError:
            row[i] = np.nan

    return row


def populate_array(input_file, primary_species=True, mineral_vols=False, ph=False):
    """Populates an empty initial condition spatial array with species and mineral data.

    Every condition block contributes the rows of the region(s) it is applied over in
    INITIAL_CONDITIONS, so a template whose first condition block is a boundary or pump condition
    with no region is handled correctly. Where regions overlap, the condition declared last in the
    input file wins. Grid cells no condition covers are left at zero, and warned about.

    Args:
        input_file: The input file containing the data for population.
        primary_species: Whether to include primary species concentrations.
        mineral_vols: Whether to include mineral volume fractions.
        ph: Whether to include pH, recorded as pH rather than as an H+ concentration.
            A condition that constrains H+ directly instead of declaring pH gets nan.

    Returns:
        numpy array with spatial initial conditions, of shape
        (number of grid cells, number of variables), with columns ordered as condition_variables()
    """
    names = condition_variables(input_file, primary_species, mineral_vols, ph)
    array = initialise_array(input_file, len(names))
    covered = np.zeros(array.shape[0], dtype=bool)

    # Construct an initial volume fraction field using initial conditions and the region attribute.
    for condition in input_file.condition_blocks:
        row_list = compute_rows(input_file, condition)
        if not row_list:
            # A condition that is never applied as an initial condition, e.g. a boundary or pump
            # condition, has no rows to fill.
            continue

        row = _condition_row(input_file, condition, names, primary_species, mineral_vols, ph)
        array[row_list] = row
        covered[row_list] = True

    if not covered.all():
        print(f'Warning: {int((~covered).sum())} of {covered.size} grid cells are not covered by any '
              f'condition region in INITIAL_CONDITIONS; their values are left at zero.')

    return array


def initialise_array(input_file, variable_num, verbose=False):
    """Returns the empty numpy array representing the coordinate grid.

    CrunchTope cycles through coordinates x -> y -> z in TecPlot output format
    so we need an array with xboxes * yboxes * zboxes number of rows and species
    number of columns. Following on from this, any coord has a row number =
    [x + (y * x_len) + (z * x_len * y_len)] in this scheme.
    (Where coord counting starts from (0, 0, 0)) Contiguous areas in real space
    are not necessarily contiguous in the row format.

    Args:
        input_file: InputFile object to construct the array for.
        variable_num: The number of variables (species, minerals) to be recorded in the array.
        verbose: Whether to print warnings about missing discretization info.

    Returns:
        numpy array of zeros with appropriate dimensions
    """
    # Initialise discretization array as CrunchTope defaults. Could probably
    # move this to be the default when input files are being read in/generated
    # but will leave here for now.
    disc = [[1, 1], [1, 1], [1, 1]]

    zone_list = ['xzones', 'yzones', 'zzones']

    try:
        for i, zone in enumerate(zone_list):
            # We ensure discretization data is read in as floats.
            disc[i] = [float(j) for j in input_file.keyword_blocks['DISCRETIZATION'].contents[zone]]
    except KeyError as error:
        if verbose:
            print(
                f"The discretization in {error.args[0]} has not been specified.\n"
                "If this is in error, check your input file.\n"
                "Otherwise, update your input file to suppress this error."
            )

    # Get the total number of rows required by the tidy data format for this geometry.
    row_count = int(disc[0][0] * disc[1][0] * disc[2][0])

    # Initialise output volume np.array and get the condition volume fractions.
    array = np.zeros((row_count, variable_num))

    return array


def compute_rows(input_file, condition):
    """Compute the list of row numbers that correspond to the regions over which the condition is specified.

    Args:
        input_file: InputFile object containing condition information
        condition: Name of the condition to compute rows for

    Returns:
        row_list: a list of integers specifying which rows in the initial state
            array correspond (in the tidy format) to the region for the initial condition.
    """
    # Any coord has a row number = [x + (y * x_len) + (z * x_len * y_len)] in
    # this scheme. (Where coord counting starts from (0, 0, 0)) Contiguous areas
    # in real space are not necessarily contiguous in the row format. Need to
    # get row numbers for each condition and each region specified to start
    # with that condition.

    condition_regions = input_file.condition_blocks[condition].region

    all_rows = []

    for region in condition_regions:

        if region == [[0, 0], [0, 0], [0, 0]]:
            print(f"Unused condition '{condition}' detected.")
            continue

        # Recall that region refers to block numbers not coordinates and that
        # counting starts from 1, so must be adjusted at start, but not the end
        # because np.arange doesn't include the final number. Lots of fence-post
        # errors to keep track of here.
        x_rows = np.arange((region[0][0] - 1), region[0][1])
        y_rows = np.arange((region[1][0] - 1), region[1][1])
        z_rows = np.arange((region[2][0] - 1), region[2][1])

        row_list_len = len(x_rows) * len(y_rows) * len(z_rows)
        # Make a list of zeros the length of row_list_len. NOT a numpy array.
        row_list = [0] * row_list_len

        # Get a list of the row indices corresponding to the region where the condition is applied.
        n = 0
        for z in z_rows:
            for y in y_rows:
                for x in x_rows:
                    row_list[n] = int(x + (y * len(x_rows)) + (z * len(y_rows) * len(z_rows)))
                    n = n + 1

        all_rows.extend(row_list)

    return all_rows
