"""CrunchTope keyword block objects clas file."""

class KeywordBlock:
    """Object describing a CT input file keyword block. An input file is comprised of many of these."""

    def __init__(self, block_type):
        self.block_type = block_type
        self.contents = {}


class ConditionBlock(KeywordBlock):
    """Object describing a CT input file keyword block. An input file is comprised of many of these."""

    def __init__(self):
        KeywordBlock.__init__(self, 'CONDITION')
        self.region = []
        self.gases = {}
        self.minerals = {}
        self.primary_species = {}
        self.parameters = {}

