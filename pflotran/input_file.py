import omphalos.keyword_block


def write_block(f, contents):
    import copy
    # Ensure that the dictionary is unpacked in the right order so that the file has the right syntax.
    for entry in contents:
        line = copy.deepcopy(contents[entry])
        line.insert(0, entry)
        line.append('\n')
        f.write(' '.join(line))
    f.write('END\n\n')


class InputFile:
    """Highest level object, representing a single PFLOTRAN input file."""

    def __init__(self, path, editable_blocks, verbatim, restarts):
        from pathlib import Path
        # Non-unique block dispatcher
        self.path = Path(path)
        self.editable_blocks = editable_blocks
        self.verbatim = verbatim
        self.results = dict()
        # 0 = successful run
        # 1 = timeout
        # 2 = condition speciation error
        # 3 = charge balance error
        # 4 = singular matrix encountered
        self.error_code = 0
        self.restart = False
        self.later_inputs = restarts

    def print(self):
        """Writes out a populated input file to a CrunchTope readable *.in file.
        """
        import pflotran.keyword_block as keyword_block

        def get_block_contents(f, nested_dict):
            if isinstance(nested_dict, keyword_block.KeywordBlock):
                # Recursively process nested dictionary
                write_block(f, nested_dict.contents)
            else:
                for key, value in nested_dict.items():
                    get_block_contents(f, nested_dict[key])

            return

        with open(self.path, 'w') as f:
            # Print simulation block.
            # Ensure that the dictionary is unpacked in the right order so that the file has the right syntax.
            subsurface_blocks = self.editable_blocks

            # Print out the subsurface cards.
            if self.verbatim:
                for line in self.verbatim.values():
                    f.write(f'{line}\n')
                    if line == 'SIMULATION' and self.restart == True:
                        self.add_restart_block(f)
            for key in subsurface_blocks:
                get_block_contents(f, subsurface_blocks[key])

            f.write('END_SUBSURFACE')
    
    def add_restart_block(self, f):
        restart_index = self.path.name.split('_', 1)[0]
        name_stem = self.path.stem.split('_', 1)[1]
        if restart_index == '0':
            return
        else:
            f.write('RESTART\n')
            f.write(f'  FILENAME {int(restart_index)-1}_{name_stem}-restart.chk\n')
            f.write('/\n')
        
            
    

    def get_results(self):
        from pathlib import Path
        import h5py as h5

        results_path = self.path.parent / Path(self.path.stem + '.h5')
        results = h5.File(results_path,  'r')

        from coeus.pflotran import h5_to_xarray

        ds = h5_to_xarray(results)
        self.results = ds
