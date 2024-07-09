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

    def __init__(self, path, simulation_block, subsurface_blocks, aqueous_database, catabolic_pathways, restarts):
        # Non-unique block dispatcher
        self.path = path
        self.simulation_blocks = simulation_block
        self.subsurface_blocks = subsurface_blocks
        # Get databases
        self.aqueous_database = aqueous_database
        self.catabolic_pathways = catabolic_pathways
        self.results = dict()
        # 0 = successful run
        # 1 = timeout
        # 2 = condition speciation error
        # 3 = charge balance error
        # 4 = singular matrix encountered
        self.error_code = 0
        self.later_inputs = restarts

    def print(self):
        """Writes out a populated input file to a CrunchTope readable *.in file.
        """

        def get_block_contents(f, nested_dict):
            if isinstance(nested_dict, omphalos.keyword_block.KeywordBlock):
                # Recursively process nested dictionary
                write_block(f, nested_dict.contents)
            else:
                for key, value in nested_dict.items():
                    get_block_contents(f, nested_dict[key])

            return

        import copy
        with open(self.path, 'w') as f:
            # Print simulation block.
            # Ensure that the dictionary is unpacked in the right order so that the file has the right syntax.
            subsurface_blocks = self.editable_blocks

            # Print out the subsurface cards.
            if self.verbatim:
                for line in self.verbatim.values():
                    f.write(f'{line}\n')
            for key in subsurface_blocks:
                print(key)
                get_block_contents(f, subsurface_blocks[key])

            f.write('END_SUBSURFACE')

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

    def get_results(self, tmp_dir):
        import pandas as pd
        import xarray as xr
        from omphalos import file_methods as fm

        times = self.keyword_blocks['OUTPUT'].contents['spatial_profile']

        # Check for later inputs and append times.
        if self.later_inputs:
            for file in self.later_inputs:
                later_times = self.later_inputs[file].keyword_blocks['OUTPUT'].contents['spatial_profile']
                times.extend(later_times)

        # Convert time strings in raw input file to floats and make into pd.Index object.
        times = [float(a) for a in times]
        times = pd.Index(data=times, name='time')

        bad_cats = ['MineralPercent', 'velocityx', 'velocityy', 'velocityz', 'MineralVolfraction', 'gases_conc']
        categories = fm.data_cats(tmp_dir)

        for bad_cat in bad_cats:
            if bad_cat in categories:
                categories.remove(bad_cat)

        for category in categories:

            print(f'Parsing {category}')
            ds_list = list()
            skip_counter = 0

            for i, time in enumerate(times):
                try:
                    ds = fm.parse_output(tmp_dir, category, i + 1)
                    ds_list.append(ds)
                except:
                    skip_counter += 1
                    print(f"WARNING: Outputs at time {time} not parsed.")

            # Don't try to concat on times that have been skipped.
            # WARNING: Will slice from the back, assuming that all failed output files are at the end
            # i.e. after a crash or timeout. I don't know why this wouldn't be the case but just in case
            # something wierd happens, maybe look here...
            # If file formatting for that output file category is bad then will try to concat nothing
            # and this will throw ValueError.
            #try:
            ds = xr.concat(ds_list, dim=times[:len(times) - skip_counter])
            self.results.update({category: ds})
            #except ValueError:
            #    print(f'WARNING: Output file {category} not parsed.')
            #    continue
