"""CrunchTope keyword block objects clas file."""


class KeywordBlock:
    """Object describing a CT input file keyword block. An input file is comprised of many of these."""

    def __init__(self, block_type):
        self.block_type = block_type
        self.contents = {}

    def modify(self, entry, value, mod_pos, species_type=None):
        """Change the parameters of a keyword block in an InputFile object.

        Args:
        """
        from omphalos.generate_inputs import get_config_array

        # Extract corresponding input file block name and the position of the variable to be modified.

        if species_type:
            raise KeywordBlockModificationError('KeywordBlock has no species_type')
            import sys
            sys.exit()

        array = self.contents[entry]
        array[mod_pos] = str(value)
        self.contents.update({entry: array})


class ConditionBlock(KeywordBlock):
    """Object describing a CT input file condition block. An input file consists of many of these."""

    def __init__(self):
        KeywordBlock.__init__(self, 'CONDITION')
        self.region = []
        self.gases = {}
        self.mineral_volumes = {}
        self.concentrations = {}
        self.parameters = {}

    def modify(self, entry, value, mod_pos, species_type=None):
        """Modify concentration based on config file.
        Requires its own method because multiple conditions may be specified."""

        if not species_type:
            raise ConditionBlockModificationError('ConditionBlock must have a species_type.')
            import sys
            sys.exit()

        contents = self.__getattribute__(species_type)

        array = contents[entry]
        array[mod_pos] = str(value)
        contents.update({entry: array})
