"""Keyword block object classes for input file representation.

These classes represent the different types of blocks found in CrunchTope
and PFLOTRAN input files.
"""


class KeywordBlockModificationError(Exception):
    """Exception raised for errors when modifying KeywordBlock objects."""
    pass


class ConditionBlockModificationError(Exception):
    """Exception raised for errors when modifying ConditionBlock objects."""
    pass


# Separator between a keyword and the token that makes its dictionary key unique, for the keywords
# CrunchTope allows to repeat within a block.
KEY_SEPARATOR = '&'

# Keywords CrunchTope allows to appear more than once within a keyword block, per the Users' Manual:
# 'Multiple specifications of time_series may occur, each one giving a different filename and node
# number'; 'Multiple exchangers can be listed'; D_25 takes one line per species. Entries are keyed on
# the leftmost word, so without a unique suffix these lines overwrite each other and all but the last
# is silently dropped from the input file written for each run. The token following the keyword names
# the thing being specified (filename or node, exchanger, species), so it makes the key unique while
# staying stable when a sweep changes the values. The suffix is stripped again when printing.
REPEATABLE_ENTRIES = {
    'OUTPUT': ('time_series',),
    'ION_EXCHANGE': ('exchange',),
    'TRANSPORT': ('D_25',),
}


def strip_entry_key(block, entry):
    """Return the keyword an entry key refers to, dropping any uniqueness suffix.

    Args:
        block: The keyword block the entry belongs to.
        entry: The entry key as stored in the block contents.

    Returns:
        The keyword to write at the start of the line.
    """
    if block in REPEATABLE_ENTRIES:
        return entry.split(KEY_SEPARATOR)[0]

    return entry

# The keywords that introduce a mineral surface area value in a condition block entry, per the
# CrunchTope Users' Manual (Mineral Surface Area Options). If none is given, a bare trailing value is
# read by CrunchTope as the bulk surface area.
SURFACE_AREA_KEYWORDS = ('bulk_surface_area', 'bsa', 'specific_surface_area', 'ssa')


def resolve_entry(contents, entry):
    """Return the key in contents that entry refers to, allowing a bare repeatable keyword.

    Repeatable keywords are stored under a composite key ('D_25&H+') so that several lines can
    coexist. A config naming the bare keyword is unambiguous only while one such line exists, which
    is the common case; if there are several the caller has to say which one it means.

    Args:
        contents: The dictionary of block entries to look the name up in.
        entry: The entry name to resolve.

    Returns:
        The matching key in contents.

    Raises:
        KeyError: If nothing matches, or if a bare keyword matches several composite keys.
    """
    if entry in contents:
        return entry

    prefix = f'{entry}{KEY_SEPARATOR}'
    matches = [key for key in contents if key.startswith(prefix)]

    if not matches:
        raise KeyError(entry)
    if len(matches) > 1:
        raise KeyError(
            f"'{entry}' matches several entries in this block: {matches}. CrunchTope allows this "
            f"keyword to repeat, so name the one you mean, e.g. '{matches[0]}'."
        )

    return matches[0]


def surface_area_position(entry, values):
    """Return the index in values holding the mineral surface area.

    The manual's format is '<phase> <volume fraction> [<surface area keyword>] <value> [<threshold>]'.
    The surface area keyword is optional, and secondary phases may carry a trailing nucleation
    threshold volume fraction, so the value's position has to be found rather than assumed: indexing
    from the end lands on the threshold when one is present.

    Args:
        entry: The mineral name, for the error message.
        values: The condition block entry for that mineral, starting at the volume fraction.

    Returns:
        The index of the surface area value in values.

    Raises:
        ConditionBlockModificationError: If the entry carries no surface area value.
    """
    for i, value in enumerate(values):
        if value in SURFACE_AREA_KEYWORDS:
            if i + 1 < len(values):
                return i + 1
            raise ConditionBlockModificationError(
                f"'{entry}' gives the surface area option '{value}' with no value after it."
            )

    # No keyword given, so CrunchTope reads a bare trailing value as the bulk surface area.
    if len(values) > 1:
        return 1

    raise ConditionBlockModificationError(
        f"'{entry}' specifies a volume fraction but no surface area, so there is no surface area to "
        f"modify. Add one to the condition block, e.g. '{entry} {values[0] if values else '0.0'} "
        f"specific_surface_area <value>'."
    )


class KeywordBlock:
    """Object describing an input file keyword block.

    An input file comprises many of these blocks, each containing specific
    configuration parameters.

    Attributes:
        block_type: The type/name of the keyword block (e.g., 'RUNTIME', 'MINERALS')
        contents: Dictionary of block entries, keyed by the leftmost word on each line
    """

    def __init__(self, block_type):
        """Initialize a KeywordBlock.

        Args:
            block_type: The type/name of the keyword block
        """
        self.block_type = block_type
        self.contents = {}

    def modify(self, entry, value, mod_pos, species_type=None):
        """Change the parameters of a keyword block in an InputFile object.

        Args:
            entry: The dictionary key for the entry to modify
            value: The new value to set (can be a single value or list)
            mod_pos: The position in the value array to modify
            species_type: Should be None for KeywordBlock (used by ConditionBlock)

        Raises:
            KeywordBlockModificationError: If species_type is provided for a KeywordBlock
        """
        if species_type:
            raise KeywordBlockModificationError(
                f'KeywordBlock has no species_type, but received: {species_type}'
            )

        entry = resolve_entry(self.contents, entry)
        array = self.contents[entry]

        # Check if assigning an entire array (e.g. if changing spatial profile).
        if isinstance(value, list):
            for i in range(len(value)):
                value[i] = str(value[i])
            array[mod_pos] = value
        else:
            array[mod_pos] = str(value)

        self.contents.update({entry: array})


class ConditionBlock(KeywordBlock):
    """Object describing a geochemical condition block.

    An input file can consist of many of these, each representing a different
    geochemical condition (e.g., seawater, initial, boundary).

    Attributes:
        block_type: Always 'CONDITION' for ConditionBlock
        contents: Raw contents of the condition block
        region: List of regions where this condition applies
        gases: Dictionary of gas species
        mineral_volumes: Dictionary of mineral volume fractions (also contains SSA data)
        concentrations: Dictionary of primary species concentrations
        exchangers: Dictionary of exchanger cation exchange capacities, keyed by exchanger name
        surface_complexes: Dictionary of surface hydroxyl site densities, keyed by site name
        parameters: Dictionary of other parameters (temperature, pH, etc.)
    """

    def __init__(self):
        """Initialize a ConditionBlock with empty dictionaries for each species type."""
        KeywordBlock.__init__(self, 'CONDITION')
        self.region = []
        self.gases = {}
        self.mineral_volumes = {}
        self.concentrations = {}
        self.exchangers = {}
        self.surface_complexes = {}
        self.parameters = {}

    # Alias for backward compatibility with existing code
    @property
    def minerals(self):
        """Alias for mineral_volumes for backward compatibility."""
        return self.mineral_volumes

    @minerals.setter
    def minerals(self, value):
        """Setter for minerals alias."""
        self.mineral_volumes = value

    def modify(self, entry, value, mod_pos, species_type=None):
        """Modify a species value based on config file.

        Requires its own method because multiple conditions may be specified
        and the entry must be looked up in the appropriate species dictionary.

        Args:
            entry: The species/parameter name to modify
            value: The new value to set
            mod_pos: The position in the value array to modify
            species_type: The type of species ('concentrations', 'mineral_volumes',
                'mineral_ssa', 'gases', 'exchangers', 'surface_complexes', 'parameters')

        Raises:
            ConditionBlockModificationError: If species_type is not provided, or if the entry
                carries no surface area to modify.
        """
        if not species_type:
            raise ConditionBlockModificationError(
                'ConditionBlock.modify() must have a species_type specified.'
            )

        # If modifying surface area, index into mineral volumes and find the value rather than
        # trusting mod_pos: it sits at a different offset depending on which of the manual's forms
        # the entry uses, and indexing from the end hits the nucleation threshold when one is given.
        if species_type == 'mineral_ssa':
            species_type = 'mineral_volumes'
            mod_pos = surface_area_position(entry, self.mineral_volumes[entry])

        # Exchangers and surface complexes used to be sorted as parameters, so a config that names
        # them under 'parameters' predates the split and still means the same entry.
        if species_type == 'parameters' and entry not in self.parameters:
            for fallback in ('exchangers', 'surface_complexes'):
                if entry in getattr(self, fallback):
                    species_type = fallback
                    break

        # Special handling for gases: first try gases dict, then search concentrations
        if species_type == 'gases':
            # First, try direct lookup in gases dictionary (original behavior)
            if entry in self.gases:
                array = self.gases[entry]
                array[mod_pos] = str(value)
                self.gases.update({entry: array})
                return

            # If not found, search concentrations for an aqueous species equilibrated with this gas
            # e.g., CO2(aq): ['CO2(g)', '0.000412'] - we want to modify '0.000412'
            for aq_species, aq_value in self.concentrations.items():
                if entry in aq_value:
                    # Found the aqueous species equilibrated with this gas
                    array = aq_value
                    array[mod_pos] = str(value)
                    self.concentrations.update({aq_species: array})
                    return

            raise ConditionBlockModificationError(
                f"Gas '{entry}' not found in gases dictionary or concentration entries. "
                f"Check that the gas exists or an aqueous species is equilibrated with it."
            )

        contents = getattr(self, species_type)

        array = contents[entry]
        array[mod_pos] = str(value)
        contents.update({entry: array})
