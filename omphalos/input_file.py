import copy
import re

import pandas as pd
import xarray as xr

from core.keyword_block import strip_entry_key
from omphalos import file_methods as fm


# Marks a line continued on the next one.
CONTINUATION = '&'

# CrunchTope reads at most this many characters from a physical line.
MAX_LINE_LENGTH = 132

# Entries whose value is a list the manual allows to be continued across lines with a trailing
# ampersand, so an over-long one can be wrapped rather than truncated by CrunchTope. Only these are
# wrapped; every other entry is written as a single line, as before.
CONTINUABLE_ENTRIES = ('spatial_profile', 'time_series_print', 'MakeMovie')


def _format_entry_line(entry, words, max_line_length=MAX_LINE_LENGTH):
    """Return the text for a keyword block entry, continued over several lines if it is too long.

    CrunchTope reads only the first 132 characters of a line, so a long list of output times has to
    be broken up. The manual's mechanism is a trailing ampersand, with the continuation carrying on
    from the next line; Template.join_continuations reads it back as one entry.

    Args:
        entry: The keyword being written, used to decide whether wrapping is allowed.
        words: The whole line, starting with the keyword.
        max_line_length: Maximum characters per physical line.

    Returns:
        The text to write, ending in a newline.
    """
    words = [str(word) for word in words]
    text = ' '.join(words)

    if len(text) <= max_line_length or entry not in CONTINUABLE_ENTRIES:
        return f'{text}\n'

    lines = []
    current = [words[0]]
    for word in words[1:]:
        # Leave room for the continuation marker this line will need if anything follows it.
        too_long = len(' '.join(current + [word, CONTINUATION])) > max_line_length
        if too_long and len(current) > 1:
            lines.append(' '.join(current + [CONTINUATION]))
            current = [word]
        else:
            current.append(word)
    lines.append(' '.join(current))

    return '\n'.join(lines) + '\n'


class InputFile:
    """Highest level object, representing a single CrunchTope input file."""

    def __init__(self, path, keyword_blocks, condition_blocks, aqueous_database, catabolic_pathways, restarts):
        self.path = path
        self.keyword_blocks = keyword_blocks
        self.condition_blocks = condition_blocks
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
        self.stage_num = None  # Stage index for staged restart runs

    def _block_entries(self, keyword):
        """Return the entry names of a keyword block, or an empty list if that block is absent.

        Not every CrunchTope input file declares every block: a problem with no gas chemistry has no GASES
        block, and one with no minerals has no MINERALS block. An absent block simply contributes no names
        to sort condition entries against.
        """
        block = self.keyword_blocks.get(keyword)
        # Making a list of a dict returns the keys, which is what callers need.
        return list(block.contents) if block is not None else []

    def _exchanger_names(self):
        """Return the exchanger names declared in the ION_EXCHANGE block.

        Entries there read 'exchange <name> [on <mineral>]', so the name is the first value rather
        than the key: the key is the repeated 'exchange' keyword plus its uniqueness suffix.
        """
        block = self.keyword_blocks.get('ION_EXCHANGE')
        if block is None:
            return []

        return [values[0] for key, values in block.contents.items()
                if key.split('&')[0] == 'exchange' and values]

    def sort_condition_block(self, condition):
        """Sort a condition block dictionary into dictionaries for each types of species (mineral, gas, aqueous,
        exchanger, surface complex, parameter).

        This is required when you need to distinguish between types of entry in a condition block.
        """
        # Get the lists of minerals, gases, and primary species for comparison. Blocks the input file does
        # not declare contribute nothing.
        # Need to strip kinetics labels from mineral names to find them in condition block.
        mineral_list = [mineral.split('&')[0] for mineral in self._block_entries('MINERALS')]
        gases_list = self._block_entries('GASES')
        primary_species_list = self._block_entries('PRIMARY_SPECIES')
        # A condition gives a cation exchange capacity for each exchanger and a site density for each
        # surface complex. Both are named in their own keyword block, so they can be told apart from
        # condition-wide parameters like units and temperature rather than being lumped in with them.
        exchanger_list = self._exchanger_names()
        surface_complex_list = self._block_entries('SURFACE_COMPLEXATION')

        if not primary_species_list:
            print(
                "Warning: no PRIMARY_SPECIES block found, so every entry in condition block "
                f"'{condition}' will be sorted as a parameter. Check the input file, or run the "
                "get_keyword_blocks() method first.")

        # For each entry in the dictionary, compare with the PRIMARY_SPECIES, MINERALS, GASES,
        # ION_EXCHANGE and SURFACE_COMPLEXATION blocks to assign the entry to the right dict.
        contents = self.condition_blocks[condition].contents
        # Maybe there is a way to make this if logic compact? Worth thinking
        # about maybe...
        for entry in contents:
            if entry in mineral_list:
                self.condition_blocks[condition].mineral_volumes.update(
                    {entry: contents[entry]})
            elif entry in gases_list:
                self.condition_blocks[condition].gases.update(
                    {entry: contents[entry]})
            elif entry in primary_species_list:
                self.condition_blocks[condition].concentrations.update(
                    {entry: contents[entry]})
            elif entry in exchanger_list:
                self.condition_blocks[condition].exchangers.update(
                    {entry: contents[entry]})
            elif entry in surface_complex_list:
                self.condition_blocks[condition].surface_complexes.update(
                    {entry: contents[entry]})
            else:
                self.condition_blocks[condition].parameters.update(
                    {entry: contents[entry]})

    def print(self):
        """Writes out a populated input file to a CrunchTope readable *.in file.
        """
        with open(self.path, 'w') as f:
            # Print out each keyword block, not condition blocks: they require
            # special treatment.
            for block in self.keyword_blocks:
                # Special treatment for the ISOTOPE block because of the way the dictionary is indexed.
                # Ensure that the dictionary is unpacked in the right order so
                # that the file has the right syntax.
                if (block == 'ISOTOPES') or (block == 'INITIAL_CONDITIONS'):
                    for entry in self.keyword_blocks[block].contents:
                        line = copy.deepcopy(self.keyword_blocks[block].contents[entry])
                        line.insert(1, entry)
                        line.append('\n')
                        f.write(' '.join(line))
                elif block == 'FLOW':
                    for entry in self.keyword_blocks[block].contents:
                        if (entry.find('permeability') != -1 or entry.find('pressure') != -1) and self.keyword_blocks[block].contents[entry][-1] != 'default':
                            line = copy.deepcopy(
                                self.keyword_blocks[block].contents[entry])
                            keyword = entry.split(' ', 1)[0]
                            coord = entry.split(' ', 1)[-1]

                            line.insert(0, keyword)
                            line.insert(3, coord)
                            line.append('\n')
                            f.write(' '.join(line))
                        elif (entry.find('pump') != -1) and self.keyword_blocks[block].contents[entry][-1] != 'default':
                            line = copy.deepcopy(
                                self.keyword_blocks[block].contents[entry])
                            keyword = entry.split('&', 1)[0]
                            coords = entry.split('&')[1:]
                            line.insert(0, keyword)
                            line[3:6] = coords
                            line.append('\n')
                            f.write(' '.join(line))
                        else:
                            line = copy.deepcopy(
                                self.keyword_blocks[block].contents[entry])
                            line.insert(0, entry)
                            line.append('\n')
                            f.write(' '.join(line))
                elif block == 'MINERALS':
                    # Need to strip kinetic labels from the dictionary entries in the mineral dict when printing.
                    for entry in self.keyword_blocks[block].contents:
                        line = copy.deepcopy(self.keyword_blocks[block].contents[entry])
                        min_name = entry.split('&')[0]
                        line.insert(0, min_name)
                        line.append('\n')
                        f.write(' '.join(line))

                else:
                    for entry in self.keyword_blocks[block].contents:
                        line = copy.deepcopy(
                            self.keyword_blocks[block].contents[entry])
                        # Repeatable keywords carry a suffix that makes their key unique; the file
                        # wants the keyword itself back at the start of the line.
                        keyword = strip_entry_key(block, entry)
                        line.insert(0, keyword)

                        f.write(_format_entry_line(keyword, line))
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
                    self.condition_blocks[block].mineral_volumes,
                    self.condition_blocks[block].exchangers,
                    self.condition_blocks[block].surface_complexes,
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
                        result = re.findall(r"\d+", coords)
                        result = list(map(int, result))
                        condition_region[i] = result

                except KeyError:
                    condition_region = [[0, 0], [0, 0], [0, 0]]
                    print(f'Warning: The condition {condition} was not specified as a initial condition')

                self.condition_blocks[condition].region.append(condition_region)

    def get_results(self, tmp_dir, file_offset=0):
        """Parse CrunchTope output files and store results.

        Args:
            tmp_dir: Directory containing output files.
            file_offset: Offset for file numbering (used in staged restarts where
                files from previous stages have already been written). Default 0.
        """
        times = self.keyword_blocks['OUTPUT'].contents['spatial_profile']

        # Check for later inputs and append times.
        if self.later_inputs:
            for file in self.later_inputs:
                later_times = self.later_inputs[file].keyword_blocks['OUTPUT'].contents['spatial_profile']
                times.extend(later_times)

        # Convert time strings in raw input file to floats and make into pd.Index object.
        times = [float(a) for a in times]
        times = pd.Index(data=times, name='time')

        bad_cats = ['MineralPercent', 'velocityx', 'velocityy', 'velocityz', 'MineralVolfraction', 'gases_conc', 'Temperature']
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
                    ds = fm.parse_output(tmp_dir, category, i + 1 + file_offset)
                    ds_list.append(ds)
                except Exception as e:
                    skip_counter += 1
                    print(f"WARNING: Outputs at time {time} not parsed. ({e})")

            # Don't try to concat on times that have been skipped.
            # WARNING: Will slice from the back, assuming that all failed output files are at the end
            # i.e. after a crash or timeout. I don't know why this wouldn't be the case but just in case
            # something wierd happens, maybe look here...
            # If file formatting for that output file category is bad then will try to concat nothing
            # and this will throw ValueError.
            #try:
            ds = xr.concat(ds_list, dim=times[:len(times)-skip_counter])
            self.results.update({category: ds})
            #except ValueError:
            #    print(f'WARNING: Output file {category} not parsed.')
            #    continue
