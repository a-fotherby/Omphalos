from pflotran.input_file import InputFile


class Template(InputFile):
    """Subclass of InputFile with special __init__ method for importing the template input file."""

    def __init__(self, config):
        import copy
        import cards

        super().__init__(config['template'], {}, {}, 0)
        # Proceed to iterate through each keyword block to import the whole file.
        # FLOW, INITIAL_CONDITION, and ISOTOPES have their own methods.

        self.config = config
        self.editable_blocks = {}
        self.later_inputs = {}
        self.raw = self.read_file(self.path)
        self.error_code = 0
        self.verbatim = copy.deepcopy(self.raw)
        # Will only have 'restart' key if it is a restart.
        # Therefore, if KeyError, not a restart.
        try:
            if self.config['restart']:
                pass
        except KeyError:
            self.config['restart'] = False

        big_blocks = ['simulation_blocks', 'subsurface_blocks']
        block_cards = [cards.simulation(), cards.subsurface()]
        big_blocks = ['editable_blocks']
        cards_to_edit = [cards.editable()]
        for block_name, card in zip(big_blocks, cards_to_edit):
            big_block = self.get_big_block(card)
            setattr(self, block_name, big_block)

        last_line, _ = self.find_blocks('END_SUBSURFACE', 'END_SUBSURFACE')
        self.verbatim.pop(last_line[0])

        # Check template is not a restart file to avoid infinite recursion.
        #if not self.config['restart']:
        #    # Check for restarts.
        #    try:
        #        later_files = self.editable_blocks['RUNTIME'].contents['later_inputfiles']
        #    except KeyError:
        #        return
        #    if later_files:
        #        print('*** Later input files found ***')
        #        for later_file in later_files:
        #            try:
        #                # By default we propagate the changes specified in the Omphalos config.
        #                # I.e. if we change a boundary condition we expect it to be the same in later restarts.
        #                # TODO: Varying conditions from the config over restarts.
        #                later_config = copy.deepcopy(self.config)
        #                later_config['template'] = later_file
        #                later_config['restart'] = True
        #                self.later_inputs.update({later_file: Template(later_config)})
        #                print(f'*** IMPORTED LATER FILE {later_file} ***')
        #            except FileNotFoundError:
        #                import __main__
        #                script_name = str(__main__.__file__).split('/')[-1]
        #                if script_name == 'make_restarts.py':
        #                    return
        #                else:
        #                    raise FileNotFoundError
        #    else:
        #        import sys
        #        sys.exit('You have specified a restart without specifying which input file to run next. Exiting.')

    @staticmethod
    def read_file(path):
        """Return a dictionary of lines in a file, with the values as the line numbers.

        Will ignore any commented lines in the CT input file, but will still count their line number,
        so line numbers in dictionary will map to the true line number in the file.
        """
        import re
        input_file = {}

        with open(path, 'r') as f:
            for line_num, line in enumerate(f):
                # Input files edited on UNIX systems have newline characters that must be stripped.
                # Also strip any trailing whitespace.
                # Look to see if line is a comment, including potential indents.
                if re.match('\s*#', line):
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
            # Whole InputFile must be a deep copy to avoid memory addressing problems associated with immutability of
            # string attributes.
            file_dict[file] = copy.deepcopy(InputFile(self.config['template'], self.editable_blocks, self.verbatim, self.later_inputs))
            file_dict[file].file_num = file

        return file_dict

    def get_card(self, keyword):
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
        import numpy as np
        from omphalos import keyword_block as kb

        block_start, block_end = self.find_blocks(keyword)
        # Set the block type using the keyword in question.
        block = kb.KeywordBlock(keyword)
        keyword_dict = {}
        mangle_count = 0
        try:
            for a in np.arange(block_start[0], block_end[0]):
                # Split the line into a list, using whitespace as the delimiter, use left most entry as dict key.
                # Commented lines are removed but line number index is preserved.
                # So put in try-except statement to ignore error thrown by missing
                # line removed due to commenting.
                try:
                    line_list = self.raw[a].split()
                    if line_list[0] == '\\':
                       line_list[0].append('_'*mangle_count)
                       mangle_count += 1

                    keyword_dict.update({line_list[0]: line_list[1:]})

                    keys_to_remove = [key for key in range(block_start, block_end + 1) if key in self.verbatim]

                    for key in keys_to_remove:
                        value = self.verbatim.pop(key)

                except BaseException:
                    print(
                        'BaseException: This is normally due to a commented line in the input file. If it is not, '
                        'something has gone really wrong!')
            block.contents = keyword_dict
        except IndexError:
            print(
                f'The keyword "{keyword}" you searched for does not exist. If you are sure that this keyword is in '
                f'your input file, check your spelling.')

        return block

    def get_big_block(self, block_cards):
        import cards
        import re

        def search_card(card_name):
            for value in self.raw.values():
                if re.match(f'\s*{card_name}', value):
                    print(card_name)
                    card = self.get_card(card_name)
                    return card
                else:
                    pass
            return None

        def process_nested_dict(nested_dict):
            new_dict = {}

            for key, value in nested_dict.items():
                if isinstance(value, dict):
                    # Recursively process nested dictionary
                    new_dict[key] = process_nested_dict(value)
                else:
                    # Process the value and store the result in the new dictionary
                    if value in cards.non_unique_cards().values():
                        card = self.get_non_unqiue_cards(value)
                        new_dict.update({key: card})
                    else:
                        card = search_card(value)
                        if card is not None:
                            new_dict[key] = card
                        else:
                            pass
            return new_dict

        big_block = process_nested_dict(block_cards)

        # Get condition couplers as they require special processing.
        for condition_coupler in cards.condition_couplers():
            big_block.update({condition_coupler: {}})
            condition_couplers = self.get_condition_couplers(cards.condition_couplers()[condition_coupler])
            big_block[condition_coupler].update(condition_couplers)

        # Get mineral kinetics as require special handling.
        if 'chemistry' in big_block and 'minerals' in big_block['chemistry']:
            mineral_names = list(big_block['chemistry']['minerals'].contents.keys())
            mineral_names.remove('MINERALS')

            #big_block['chemistry']['mineral_kinetics'] = get_mineral_kinetics(mineral_names)

        return big_block

    def find_blocks(self, start_string, end_string='END', whitespace=True):
        import file_methods as fm
        import numpy as np
        # Get all instances of the keyword in question, in a numpy array.
        block_start = fm.search_file(self.raw, start_string, allow_white_space=whitespace)
        # Get array of line numbers for the END statements in the input file.
        # All CT input file keyword blocks end with 'END'.
        ending_array = fm.search_file(self.raw, end_string, allow_white_space=whitespace)
        # Find the index for the END line corresponding to the block of
        # interest.
        block_end = ending_array[np.searchsorted(ending_array, block_start)]

        return block_start, block_end

    def get_non_unqiue_cards(self, card):
        """Special method for getting all non-unique blocks from an input file, of which there may be multiple.
        'Non-unqiue blocks' are those which appear multiple times and have a user defined name.

        Assigns each block to a dictionary in the InputFile object specifically for that condition type.
        The key for each dictionary entry is the condition name specified in the input file.
        """
        from keyword_block import KeywordBlock
        import numpy as np

        block_start, block_end = self.find_blocks(card)

        non_unique_blocks = {}
        for start, end in zip(block_start, block_end):
            # Set the block type using the keyword in question.
            block_name = self.raw[start].split()[1]
            block = KeywordBlock(card)
            keyword_dict = {}
            for a in np.arange(start, end):
                # Split the line into a list, using whitespace as the delimiter, use left most entry as dict key.
                # Commented lines are removed but line number index is preserved.
                # So put in try-except statement to ignore error thrown by
                # missing line removed due to commenting.
                try:
                    line_list = self.raw[a].split()
                    keyword_dict.update({line_list[0]: line_list[1:]})
                    keys_to_remove = [key for key in range(block_start[0], block_end[-1] + 1) if key in self.verbatim]

                    for key in keys_to_remove:
                        value = self.verbatim.pop(key)
                except IndexError:
                    pass
                except KeyError:
                    pass

            block.contents = keyword_dict
            non_unique_blocks.update({block_name: block})

        return non_unique_blocks

    def get_condition_couplers(self, condition_coupler):
        """Special method for parsing condition coupler blocks from an input file, of which there may be multiple.
        All condition couplers apply conditions (e.g. FLOW_CONDITION, MATERIAL) to regions. If a region is used twice
        then it is overwritten the second time. Therefor regions can be used to uniquely identify condition
        coupler blocks. This requires a special parser.
        """
        from keyword_block import KeywordBlock
        import numpy as np

        block_start, block_end = self.find_blocks(condition_coupler, whitespace=False)

        condition_couplers = {}
        for start, end in zip(block_start, block_end):
            # Set the block type using the keyword in question.
            block = KeywordBlock(condition_coupler)
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
            block_name = keyword_dict['REGION'][0]

            block.contents = keyword_dict
            condition_couplers.update({block_name: block})

        return condition_couplers

    def get_verbatim(self, verbatim_list):
        """Bodge for right now as structure is complicated and don't actually require editing power for it."""
        verbatim = {}

        for card in verbatim_list:
            block_start, block_end = self.find_blocks(card)
            block_start = block_start[0]
            block_end = block_end[-1]

            #assert (len(block_start) == 1)
            #assert (len(block_end) == 1)

            verbatim.update({k: self.raw[k] for k in range(int(block_start), int(block_end) + 1) if k in self.raw})

        return verbatim
