import extractInputData as eid
import numpy as np

class inputFile:
    """Highest level object, representing a single CrunchTope input file."""
    def __init__(self, name, filePath):
        self.ID = name
        self.path = filePath
        self.raw = eid.importFile(self.path)
        self.keywordBlocks = {}
        
    def getKeywordBlock(self, inputFile, keyword):
        """Method to get a keyword block from the input file, specified by keyword.
        
        Creates a block object which is added to the dictionary of keyword blocks in the inputFile object.
        The block object contains the pertinent information from that keyword block in the input file.
        
        The information from the keyword block is stored in a dictionary, 
        indexed by the left most word on the line in the input file.
        
        The dictionary entry itself is the remaining contents of the line stored as a list.
        Each entry of the list is a single word from the input file line, split by whitespace.
        """
        # Get all instances of the keyword in question, in a numpy array.
        blockStart = eid.searchInputFile(inputFile, keyword)

        # Get array of line numbers for the END statements in the input file.
        # All CT input file keyword blocks end with 'END'.
        endingArray = eid.searchInputFile(inputFile, 'END')

        # Find the index for the END line corresponding to the block of interest.
        blockEnd = endingArray[np.searchsorted(endingArray, blockStart)]

        for startLN, endLN in zip(blockStart, blockEnd):
            # Set the block type using the keyword in question.
            block = keywordBlock(keyword)
            keywordDict = {}
            for a in np.arange(startLN, endLN):
                # Split the line into a list, using whitespace as the delimiter, use left most entry as dict key.
                lineList = inputFile[a].split()
                # Commented lines are removed but line number index is preserved.
                # So put in try-except statement to ignore error thrown by missing line removed due to commenting.
                try:
                    keywordDict.update({lineList[0] : lineList[1:]})
                except:
                    pass
            
            block.contentDict = keywordDict
        self.keywordBlocks.update({keyword : block})
        
class keywordBlock:
    """Object describing a CT input file keyword block. An input file is comprised of many of these."""
    def __init__(self, blockType):
        self.blockType = blockType