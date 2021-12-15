"""CrunchTope keyword block objects clas file."""


class KeywordBlock:
    """Object describing a CT input file keyword block. An input file is comprised of many of these."""

    def __init__(self, block_type):
        self.block_type = block_type
        self.contents = {}

    def modify(self, file_num, config, config_key, mod_pos):
        """Change the parameters of a keyword block in an InputFile object.

        Args:
        input_file -- The InputFile to be modified.
        config --  The config file dict containing the modifications to be made.
        config_key -- Key indexing which entry in the config file is in question.
        """
        from omphalos.generate_inputs import get_config_value

        # Extract corresponding input file block name and the position of the variable to be modified.

        for file_key in self.contents.keys():
            # Iterate over the keywords in the keyword block.
            value_to_assign = get_config_value(file_key, config, config[config_key], file_num,
                                               self)
            if value_to_assign is None:
                continue
            file_value = self.contents[file_key]
            file_value[mod_pos] = str(value_to_assign)
            self.contents.update({file_key: file_value})


class ConditionBlock(KeywordBlock):
    """Object describing a CT input file condition block. An input file consists of many of these."""

    def __init__(self):
        KeywordBlock.__init__(self, 'CONDITION')
        self.region = []
        self.gases = {}
        self.minerals = {}
        self.concentrations = {}
        self.parameters = {}

    def modify(self, config, species_type, file_num, mod_pos):
        """Modify concentration based on config file.
        Requires its own method because multiple conditions may be specified."""
        from omphalos.generate_inputs import get_config_value

        for condition in config[species_type]:
            condition_block_sec = {'concentrations': self.concentrations,
                                   'mineral_volumes': self.minerals,
                                   'gases': self.gases,
                                   'parameters': self.parameters}
            for species in condition_block_sec[species_type]:
                value_to_assign = get_config_value(species, config, config[species_type][condition], file_num,
                                                   condition_block_sec[species_type])
                if value_to_assign is None:
                    continue
                file_value = condition_block_sec[species_type][species]
                file_value[mod_pos] = str(value_to_assign)
                condition_block_sec[species_type].update({species: file_value})
