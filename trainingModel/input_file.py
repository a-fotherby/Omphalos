import file_methods as fm
import numpy as np
import pandas as pd
import copy


class InputFile:
    """Highest level object, representing a single CrunchTope input file."""

    def __init__(self, file_path):
        self.path = file_path
        self.raw = fm.import_file(self.path)
        self.keyword_blocks = {}
        self.condition_blocks = {}

    def get_keyword_block(self, keyword):
        """Method to get a keyword block from the input file, specified by keyword.

        Creates a block object which is added to the dictionary of keyword blocks in the inputFile object.
        The block object contains the pertinent information from that keyword block in the input file.

        The information from the keyword block is stored in a dictionary,
        indexed by the left most word on the line in the input file.

        The dictionary entry itself is the remaining contents of the line stored as a list.
        Each entry of the list is a single word from the input file line, split by whitespace.

        This method works for all keyword blocks except conditions, of which there may be multiple in an input file.
        In the event that a keyword block is erroneously added more than once in the input file, it will use the first instance of that keyword for assignment.
        """
        # Get all instances of the keyword in question, in a numpy array.
        block_start = fm.search_input_file(self.raw, keyword)

        # Get array of line numbers for the END statements in the input file.
        # All CT input file keyword blocks end with 'END'.
        ending_array = fm.search_input_file(self.raw, 'END')

        # Find the index for the END line corresponding to the block of
        # interest.
        block_end = ending_array[np.searchsorted(ending_array, block_start)]

        # Set the block type using the keyword in question.
        block = KeywordBlock(keyword)
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
                    print('BaseException: This is normally due to a commented line in the input file. If it is not, something has gone really wrong!')
                block.contents = keyword_dict
                self.keyword_blocks.update({keyword: block})
        except IndexError:
            print('The keyword "{}" you searched for does not exist. If you are sure that this keyword is in your input file, check your spelling.'.format(keyword))

    def get_condition_blocks(self):
        """Special method for getting all CONDITION blocks from an input file, of which there may be multiple.

        Assigns each CONDITION block to a dictionary in the inputFile object specifically for geochemical conditions.
        The key for each dictionary entry is the condition name specified in the CunchTope input file.
        """
        # Get all instances of the keyword in question, in a numpy array.
        block_start = fm.search_input_file(self.raw, 'CONDITION')

        # Get array of line numbers for the END statements in the input file.
        # All CT input file keyword blocks end with 'END'.
        ending_array = fm.search_input_file(self.raw, 'END')

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
            
    def get_isotope_block(self):
        """Method to get the isotope block from the input file and encode it as a KeywordBlock object in the InputFile.

        We have to do this in a seperate method because the isotope block is unique in CrunchTope because it has non-unique left-most words (either 'primary' or 'mineral').
        This means that the dictionary keys keep overwriting each other, so we use the rare mineral entry as the dict key instead.
        """
        # Get all instances of the keyword in question, in a numpy array.
        keyword = 'ISOTOPES'
        block_start = fm.search_input_file(self.raw, keyword)

        # Get array of line numbers for the END statements in the input file.
        # All CT input file keyword blocks end with 'END'.
        ending_array = fm.search_input_file(self.raw, 'END')

        # Find the index for the END line corresponding to the block of
        # interest.
        block_end = ending_array[np.searchsorted(ending_array, block_start)]

        # Set the block type using the keyword in question.
        block = KeywordBlock(keyword)
        keyword_dict = {}
        try:
            for a in np.arange(block_start[0], block_end[0]):
                # Split the line into a list, using whitespace as the delimiter, and use the second left most word as the dict key (in this specific context, the rare isotope)
                # Commented lines are removed but line number index is preserved.
                # So put in try-except statement to ignore error thrown by missing
                # line removed due to commenting.
                try:
                    line_list = self.raw[a].split()
                    reordered_list = [line_list[0]] + line_list[2:]
                    keyword_dict.update({line_list[1]: reordered_list})
                except IndexError:
                    # The block keyword is by itself, so there is no rare isotope keyword to use as a key.
                    # This will raise an IndexError, so catch it and allocate the dict entries accordingly.
                    keyword_dict.update({line_list[0]: line_list[1:]})
                except BaseException:
                    print('BaseException: this is normally due to a commented line in the input file. If it is not, something has gone really wrong!')
                block.contents = keyword_dict
                self.keyword_blocks.update({keyword: block})
        except IndexError:
            print('The keyword "ISOTOPES" you searched for does not exist. If you are sure that this keyword is in your input file, check your spelling.')

    def sort_condition_block(self, condition):
        """Sort a conditon block dictionary into dictionaries for each types of species (mineral, gas, aqueous, parameter).

        This is required when you need to distinguish between types of entry in a condition block.
        """
        # Try and get the lists of minerals, gases, and primary species for
        # comparison. Raise an exception otherwise.
        try:
            mineral_list = self.keyword_blocks['MINERALS'].contents.keys()
            gases_list = self.keyword_blocks['GASES'].contents.keys()
            primary_species_list = self.keyword_blocks['PRIMARY_SPECIES'].contents.keys()
        except IndexError:
            print("You must populate your MINERAL, GASES, and PRIMARY_SPECIES keyword blocks before you can sort a condition block.\nTry running the get_keyword_blocks() method first.")
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
                self.condition_blocks[condition].primary_species.update(
                    {entry: contents[entry]})
            else:
                self.condition_blocks[condition].parameters.update(
                    {entry: contents[entry]})

    def print_input_file(self):
        """Writes out a populated input file to a CrunchTope readable *.in file.

        """
        with open(self.path, 'x') as f:
            # Print out each keyword block, not condition blocks: they require special treatment.
            for block in self.keyword_blocks:
                # Special treatment for the ISOTOPE block becuase of the way the dictionary is indexed.
                # Ensure that the dictionary is unpacked in the right order so that the file has the right syntax.
                if block == 'ISOTOPES':
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
                # Originally this was done to all ConditionBlock objects but this was overwriting data from gi.create_condition_series because the original template is still stored in ConditionBlock.contents.
                if bool(self.condition_blocks[block].parameters) == False:
                    self.sort_condition_block(block)
                else:
                    pass
                for species_type in [
                    self.condition_blocks[block].parameters,
                    self.condition_blocks[block].primary_species,
                    self.condition_blocks[block].gases,
                    self.condition_blocks[block].minerals,
                ]:
                    for entry in species_type:
                        # Ugh, weird workaround because of various type error - need to be a string to compose the line, but I want to store as number for data analysis purposes.
                        # This might come back to bite later, so if things start going tits up maybe check here first for any type-casting fuckery.
                        line = copy.deepcopy(species_type[entry])
                        string = entry
                        for word in line:
                            string += (' ' + str(word))
                        
                        f.write(string + '\n')
                f.write('END\n\n')
                
    
    def calculate_mineral_diff(self, condition):
        """Calculate the total mineral volume evolution over the run.
        
        Currently only able to handle a single, uniform geochemical condition for the entire system.
        Keyword arguments:
        condition -- the dictionary entry key for the condition in question.
        """
        if bool(self.condition_blocks[condition].parameters) == False:
            self.sort_condition_block(condition)
        else:
            pass
        mineral_dict = self.condition_blocks[condition].minerals
        for key in mineral_dict:
            mineral_dict.update({key: mineral_dict[key][0]})
            
        mineral_vol_init = pd.DataFrame(mineral_dict, index=[0], dtype = float)
        mineral_vol_out = self.results.results_dict['volume'].iloc[:, 3:]
        delta_mineral_vol= mineral_vol_init - mineral_vol_out
        
        return delta_mineral_vol

    
                
class KeywordBlock:
    """Object describing a CT input file keyword block. An input file is comprised of many of these."""

    def __init__(self, block_type):
        self.block_type = block_type
        self.contents = {}


class ConditionBlock(KeywordBlock):
    """Object describing a CT input file keyword block. An input file is comprised of many of these."""

    def __init__(self):
        KeywordBlock.__init__(self, 'CONDITION')
        self.gases = {}
        self.minerals = {}
        self.primary_species = {}
        self.parameters = {}
