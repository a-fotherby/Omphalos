class inputFile:
    """Highest level object, representing a single CrunchTope input file."""
    def __init__(self, name):
        self.ID = name
        
class keywordBlock:
    """Object describing a CT input file keyword block. An input file is comprised of many of these."""
    def __init__(self, blockType):
        self.blockType = blockType
        