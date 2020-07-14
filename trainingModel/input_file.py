import file_methods as fm
import numpy as np

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
        In the event that a keyword block is erroneously added more than once, it will use the first instance of that keyword for assignment.
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
                    pass
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


class KeywordBlock:
    """Object describing a CT input file keyword block. An input file is comprised of many of these."""

    def __init__(self, block_type):
        self.block_type = block_type
        self.contents = {}


class ConditionBlock(KeywordBlock):
    """Object describing a CT input file keyword block. An input file is comprised of many of these."""

    def __init__(self):
        KeywordBlock.__init__(self, 'CONDITION')
