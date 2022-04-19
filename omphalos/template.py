from omphalos.input_file import InputFile


class Template(InputFile):
    """Subclass of InputFile with special __init__ method for importing the template input file."""

    def __init__(self, config):
        from omphalos.namelist import CrunchNameList

        super().__init__(config['template'], {}, {}, {}, {})
        # Proceed to iterate through each keyword block to import the whole file.
        keyword_list = [
            'TITLE',
            'RUNTIME',
            'OUTPUT',
            'DISCRETIZATION',
            'PRIMARY_SPECIES',
            'SECONDARY_SPECIES',
            'GASES',
            'MINERALS',
            'AQUEOUS_KINETICS',
            'ION_EXCHANGE',
            'SURFACE_COMPLEXATION',
            'BOUNDARY_CONDITIONS',
            'TRANSPORT',
            'FLOW',
            'TEMPERATURE',
            'POROSITY',
            'PEST',
            'EROSION/BURIAL']
        self.config = config
        self.raw = self.read_file(self.path)
        self.error_code = 0
        for keyword in keyword_list:
            self.get_keyword_block(keyword)

        # Get=l keyword blocks that require unique handling due to format.
        self.get_initial_conditions_block()
        self.get_isotope_block()
        self.get_condition_blocks()

        if config['aqueous_database']:
            self.aqueous_database = CrunchNameList(config['aqueous_database'])
        if config['catabolic_pathways']:
            self.catabolic_pathways = CrunchNameList(config['catabolic_pathways'])

    @staticmethod
    def read_file(path):
        """Return a dictionary of lines in a file, with the values as the line numbers.

        Will ignore any commented lines in the CT input file, but will still count their line number,
        so line numbers in dictionary will map to the true line number in the file.
        """
        input_file = {}

        with open(path, 'r') as f:
            for line_num, line in enumerate(f):
                # Input files edited on UNIX systems have newline characters that must be stripped.
                # Also strip any trailing whitespace.
                if line.startswith('!'):
                    # It's a commented line, so don't import.
                    pass
                else:
                    input_file.update({line_num: line.rstrip('\n ')})

            f.close()
        return input_file

    def make_dict(self):
        """Returns a dict of InputFile objects, based on the Template."""
        import numpy as np
        import copy

        file_dict = dict.fromkeys(np.arange(self.config['number_of_files']))
        for file in file_dict:
            file_dict[file] = InputFile(f'input_file{file}', copy.deepcopy(self.keyword_blocks),
                                        copy.deepcopy(self.condition_blocks), copy.deepcopy(self.aqueous_database),
                                        copy.deepcopy(self.catabolic_pathways))
            file_dict[file].file_num = file

        return file_dict

    def get_keyword_block(self, keyword):
        """Method to get a keyword block from the input file, specified by keyword.

        Creates a block object which is added to the dictionary of keyword blocks in the inputFile object.
        The block object contains the pertinent information from that keyword block in the input file.

        The information from the keyword block is stored in a dictionary,
        indexed by the left most word on the line in the input file.

        The dictionary entry itself is the remaining contents of the line stored as a list.
        Each entry of the list is a single word from the input file line, split by whitespace.

        This method works for all keyword blocks except conditions, of which there may be multiple in an input file.
        In the event that a keyword block is erroneously added more than once in the input file, it will use the
        first instance of that keyword for assignment.
        """
        from omphalos import file_methods as fm
        import numpy as np
        from omphalos import keyword_block as kb

        # Get all instances of the keyword in question, in a numpy array.
        block_start = fm.search_file(self.raw, keyword)
        # Get array of line numbers for the END statements in the input file.
        # All CT input file keyword blocks end with 'END'.
        ending_array = fm.search_file(self.raw, 'END')
        # Find the index for the END line corresponding to the block of
        # interest.
        block_end = ending_array[np.searchsorted(ending_array, block_start)]
        # Set the block type using the keyword in question.
        block = kb.KeywordBlock(keyword)
        keyword_dict = {}

        try:
            for a in np.arange(block_start[0], block_end[0]):
                # Split the line into a list, using whitespace as the delimiter, use left most entry as dict key.
                # Commented lines are removed but line number index is preserved.
                # So put in try-except statement to ignore error thrown by missing
                # line removed due to commenting.
                try:
                    line_list = self.raw[a].split()
                    keyword_dict.update({line_list[0]: line_list[1:]})
                except BaseException:
                    print(
                        'BaseException: This is normally due to a commented line in the input file. If it is not, '
                        'something has gone really wrong!')
                block.contents = keyword_dict
                self.keyword_blocks.update({keyword: block})
        except IndexError:
            print(
                'The keyword "{}" you searched for does not exist. If you are sure that this keyword is in your input '
                'file, check your spelling.'.format(keyword))

    def get_condition_blocks(self):
        """Special method for getting all CONDITION blocks from an input file, of which there may be multiple.

        Assigns each CONDITION block to a dictionary in the inputFile object specifically for geochemical conditions.
        The key for each dictionary entry is the condition name specified in the CrunchTope input file.
        """
        from omphalos import file_methods as fm
        from omphalos.keyword_block import ConditionBlock
        import numpy as np

        # Get all instances of the keyword in question, in a numpy array.
        block_start = fm.search_file(self.raw, 'CONDITION')
        # Get array of line numbers for the END statements in the input file.
        # All CT input file keyword blocks end with 'END'.
        ending_array = fm.search_file(self.raw, 'END')
        # Find the index for the END line corresponding to the block of
        # interest.
        block_end = ending_array[np.searchsorted(ending_array, block_start)]

        for start, end in zip(block_start, block_end):
            # Set the block type using the keyword in question.
            condition_name = self.raw[start].split()[1]
            condition = ConditionBlock()
            keyword_dict = {}
            for a in np.arange(start, end):
                # Split the line into a list, using whitespace as the delimiter, use left most entry as dict key.
                # Commented lines are removed but line number index is preserved.
                # So put in try-except statement to ignore error thrown by
                # missing line removed due to commenting.
                try:
                    line_list = self.raw[a].split()
                    keyword_dict.update({line_list[0]: line_list[1:]})
                except BaseException:
                    pass

            condition.contents = keyword_dict
            self.condition_blocks.update({condition_name: condition})

        # Get regions for each condition block.
        self.condition_regions()

    def get_isotope_block(self):
        """Method to get the isotope block from the input file and encode it as a KeywordBlock object in the InputFile.

        We have to do this in a separate method because the isotope block is unique in CrunchTope because it has
        non-unique left-most words (either 'primary' or 'mineral'). This means that the dictionary keys keep
        overwriting each other, so we use the rare mineral entry as the dict key instead.
        """
        from omphalos import file_methods as fm
        from omphalos import keyword_block as kb
        import numpy as np

        # Get all instances of the keyword in question, in a numpy array.
        keyword = 'ISOTOPES'
        block_start = fm.search_file(self.raw, keyword)

        # Get array of line numbers for the END statements in the input file.
        # All CT input file keyword blocks end with 'END'.
        ending_array = fm.search_file(self.raw, 'END')

        # Find the index for the END line corresponding to the block of
        # interest.
        block_end = ending_array[np.searchsorted(ending_array, block_start)]

        # Set the block type using the keyword in question.
        block = kb.KeywordBlock(keyword)
        keyword_dict = {}
        try:
            for a in np.arange(block_start[0], block_end[0]):
                # Split the line into a list, using whitespace as the delimiter, and use the second left most word as
                # the dict key (in this specific context, the rare isotope) Commented lines are removed but line
                # number index is preserved. So put in try-except statement to ignore error thrown by missing line
                # removed due to commenting.
                try:
                    line_list = self.raw[a].split()
                    reordered_list = [line_list[0]] + line_list[2:]
                    keyword_dict.update({line_list[1]: reordered_list})
                except IndexError:
                    # The block keyword is by itself, so there is no rare isotope keyword to use as a key.
                    # This will raise an IndexError, so catch it and allocate
                    # the dict entries accordingly.
                    keyword_dict.update({line_list[0]: line_list[1:]})
                except BaseException:
                    print(
                        'BaseException: this is normally due to a commented line in the input file. If it is not, '
                        'something has gone really wrong!')
                block.contents = keyword_dict
                self.keyword_blocks.update({keyword: block})
        except IndexError:
            print(
                'The keyword "ISOTOPES" you searched for does not exist. If you are sure that this keyword is in your '
                'input file, check your spelling.')

    def get_initial_conditions_block(self):
        """Method to get the initial conditions block from the input file and encode it as a KeywordBlock object in
        the InputFile.

        We have to do this in a separate method because the initial conditions block is unique in CrunchTope as
        conditions can be repeated to form non-contiguous regions, so the left most word is not always unique. This
        means that the dictionary keys are overwriting each other.
        """
        from omphalos import file_methods as fm
        from omphalos import keyword_block as kb
        import numpy as np
        import re
        # Get all instances of the keyword in question, in a numpy array.
        keyword = 'INITIAL_CONDITIONS'
        block_start = fm.search_file(self.raw, keyword)

        # Get array of line numbers for the END statements in the input file.
        # All CT input file keyword blocks end with 'END'.
        ending_array = fm.search_file(self.raw, 'END')

        # Find the index for the END line corresponding to the block of
        # interest.
        block_end = ending_array[np.searchsorted(ending_array, block_start)]

        # Set the block type using the keyword in question.
        block = kb.KeywordBlock(keyword)
        keyword_dict = {}
        try:
            for a in np.arange(block_start[0], block_end[0]):
                # Split the line into a list, using whitespace as the delimiter, and use the second left most word as
                # the dict key (in this specific context, the rare isotope) Commented lines are removed but line
                # number index is preserved. So put in try-except statement to ignore error thrown by missing line
                # removed due to commenting.
                try:
                    line_list = self.raw[a].split()
                    # Regex extracts keys as unique coordinate sets.
                    key = re.findall("\d+-\d+", self.raw[a])
                    key = ' '.join(key)
                    # Check to see if the fix keyword has been invoked.
                    if line_list[-1] == 'fix':
                        entry = [line_list[0]] + [line_list[-1]]
                    else:
                        entry = [line_list[0]]
                    keyword_dict.update({key: entry})
                except IndexError:
                    # The block keyword is by itself, so there is no coordinate to use as a key.
                    # This will raise an IndexError, so catch it and allocate
                    # the dict entries accordingly.
                    keyword_dict.update({line_list[0]: line_list[1:]})
                except BaseException:
                    print(
                        'BaseException: this is normally due to a commented line in the input file. If it is not, '
                        'something has gone really wrong!')
                block.contents = keyword_dict
                self.keyword_blocks.update({keyword: block})
        except IndexError:
            print('The keyword "INITIAL_CONDITIONS" you searched for does not exist; check your input file for errors.')
