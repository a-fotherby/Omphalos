"""CrunchTope keyword block objects clas file."""


class KeywordBlock:
    """Object describing a CT input file keyword block. An input file is comprised of many of these."""

    def __init__(self, block_type):
        self.block_type = block_type
        self.contents = {}


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
