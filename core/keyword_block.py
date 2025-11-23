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
        parameters: Dictionary of other parameters (temperature, pH, etc.)
    """

    def __init__(self):
        """Initialize a ConditionBlock with empty dictionaries for each species type."""
        KeywordBlock.__init__(self, 'CONDITION')
        self.region = []
        self.gases = {}
        self.mineral_volumes = {}
        self.concentrations = {}
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
                'mineral_ssa', 'gases', 'parameters')

        Raises:
            ConditionBlockModificationError: If species_type is not provided
        """
        if not species_type:
            raise ConditionBlockModificationError(
                'ConditionBlock.modify() must have a species_type specified.'
            )

        # If modifying specific surface area, need to ensure we index into mineral volumes.
        if species_type == 'mineral_ssa':
            species_type = 'mineral_volumes'

        contents = getattr(self, species_type)

        array = contents[entry]
        array[mod_pos] = str(value)
        contents.update({entry: array})
