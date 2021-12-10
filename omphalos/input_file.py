class InputFile:
    """Highest level object, representing a single CrunchTope input file."""

    def __init__(self, path, keyword_blocks, condition_blocks, aqueous_database, catabolic_pathways):
        self.path = path
        self.keyword_blocks = keyword_blocks
        self.condition_blocks = condition_blocks
        self.aqueous_database = aqueous_database
        self.catabolic_pathways = catabolic_pathways
        self.timeout = False

    def sort_condition_block(self, condition):
        """Sort a condition block dictionary into dictionaries for each types of species (mineral, gas, aqueous,
        parameter).

        This is required when you need to distinguish between types of entry in a condition block.
        """
        # Try and get the lists of minerals, gases, and primary species for
        # comparison. Raise an exception otherwise.
        try:
            mineral_list = self.keyword_blocks['MINERALS'].contents.keys()
            gases_list = self.keyword_blocks['GASES'].contents.keys()
            primary_species_list = self.keyword_blocks['PRIMARY_SPECIES'].contents.keys(
            )
        except IndexError:
            print(
                "You must populate your MINERAL, GASES, and PRIMARY_SPECIES keyword blocks before you can sort a "
                "condition block.\nTry running the get_keyword_blocks() method first.")
            # For each entry in the dictionary, compare with the PRIMARY_SPECIES,
        # MINERALS, and GASES blocks to assign the entry to the right dict.
        contents = self.condition_blocks[condition].contents
        # Maybe there is a way to make this if logic compact? Worth thinking
        # about maybe...
        for entry in contents:
            if entry in mineral_list:
                self.condition_blocks[condition].minerals.update(
                    {entry: contents[entry]})
            elif entry in gases_list:
                self.condition_blocks[condition].gases.update(
                    {entry: contents[entry]})
            elif entry in primary_species_list:
                self.condition_blocks[condition].concentrations.update(
                    {entry: contents[entry]})
            else:
                self.condition_blocks[condition].parameters.update(
                    {entry: contents[entry]})

    def print_input_file(self):
        """Writes out a populated input file to a CrunchTope readable *.in file.

        """
        import copy
        with open(self.path, 'x') as f:
            # Print out each keyword block, not condition blocks: they require
            # special treatment.
            for block in self.keyword_blocks:
                # Special treatment for the ISOTOPE block because of the way the dictionary is indexed.
                # Ensure that the dictionary is unpacked in the right order so
                # that the file has the right syntax.
                if (block == 'ISOTOPES') or (block == 'INITIAL_CONDITIONS'):
                    for entry in self.keyword_blocks[block].contents:
                        line = copy.deepcopy(
                            self.keyword_blocks[block].contents[entry])
                        line.insert(1, entry)
                        line.append('\n')
                        f.write(' '.join(line))
                else:
                    for entry in self.keyword_blocks[block].contents:
                        line = copy.deepcopy(
                            self.keyword_blocks[block].contents[entry])
                        line.insert(0, entry)
                        line.append('\n')
                        f.write(' '.join(line))
                f.write('END\n\n')

            for block in self.condition_blocks:
                # Check to see if the condition block has been sorted before. If not then sort it.
                # Originally this was done to all ConditionBlock objects but
                # this was overwriting data from gi.create_condition_series
                # because the original template is still stored in
                # ConditionBlock.contents.
                if not bool(self.condition_blocks[block].parameters):
                    self.sort_condition_block(block)
                else:
                    pass
                for species_type in [
                    self.condition_blocks[block].parameters,
                    self.condition_blocks[block].concentrations,
                    self.condition_blocks[block].gases,
                    self.condition_blocks[block].minerals,
                ]:
                    for entry in species_type:
                        # Ugh, weird workaround because of various type error - need to be a string to compose the
                        # line, but I want to store as number for data analysis purposes. This might come back to
                        # bite later, so if things start going tits up maybe check here first for any type-casting
                        # fuckery.
                        line = copy.deepcopy(species_type[entry])
                        string = entry
                        for word in line:
                            string += (' ' + str(word))

                        f.write(string + '\n')
                f.write('END\n\n')

    def check_condition_sort(self, condition):
        """Check to see if the condition block has been sorted. If not, sort it."""
        if not bool(self.condition_blocks[condition].parameters):
            self.sort_condition_block(condition)
        else:
            pass

    def condition_regions(self):
        """Find the coordinates over which condition is initially applied and assign them to the region attribute of
        the ConditionBlock object.
        
        Condition region is an ordered array of arrays, corresponding to the range over which that condition is
        applied in X, Y, and Z.
        """
        # Initialise all the region attributes to prevent infinitely appending lists.
        import re
        for condition in self.condition_blocks:
            self.condition_blocks[condition].region = []

        for coord_string in self.keyword_blocks['INITIAL_CONDITIONS'].contents:
            # Skip the block title line.
            if not coord_string:
                pass
            else:
                condition = self.keyword_blocks['INITIAL_CONDITIONS'].contents[coord_string][0]
                condition_region = [[1, 1], [1, 1], [1, 1]]
                try:
                    coord_pairs = coord_string.split()
                    for i, coords in enumerate(coord_pairs):
                        result = re.findall("\d+", coords)
                        result = list(map(int, result))
                        condition_region[i] = result

                except KeyError:
                    condition_region = [[0, 0], [0, 0], [0, 0]]
                    print(f'Warning: The condition {condition} was not specified as a initial condition')

                self.condition_blocks[condition].region.append(condition_region)
