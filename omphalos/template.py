import copy
import re
import sys

import numpy as np

from omphalos import file_methods as fm
from omphalos import keyword_block as kb
from omphalos.input_file import InputFile
from omphalos.keyword_block import ConditionBlock
from omphalos.database import Database
from omphalos.namelist import CrunchNameList

from core.keyword_block import KEY_SEPARATOR, REPEATABLE_ENTRIES
from omphalos.input_file import CONTINUATION


def block_entry_key(keyword, line_list):
    """Return the dictionary key for a line inside the named keyword block.

    Repeatable keywords get a composite key so that several of them can coexist; everything else is
    keyed on its leftmost word as before.

    Args:
        keyword: The keyword block the line belongs to.
        line_list: The line, split into words.

    Returns:
        The key to store the entry under.
    """
    name = line_list[0]

    if name in REPEATABLE_ENTRIES.get(keyword, ()) and len(line_list) > 1:
        return f'{name}{KEY_SEPARATOR}{line_list[1]}'

    return name


class Template(InputFile):
    """Subclass of InputFile with special __init__ method for importing the template input file."""

    def __init__(self, config):
        super().__init__(config['template'], {}, {}, {}, {}, 0)
        # Proceed to iterate through each keyword block to import the whole file.
        # FLOW, INITIAL_CONDITION, and ISOTOPES have their own methods.
        keyword_list = [
            'TITLE',
            'RUNTIME',
            'OUTPUT',
            'DISCRETIZATION',
            'PRIMARY_SPECIES',
            'SECONDARY_SPECIES',
            'GASES',
            'AQUEOUS_KINETICS',
            'ION_EXCHANGE',
            'SURFACE_COMPLEXATION',
            'BOUNDARY_CONDITIONS',
            'TRANSPORT',
            'TEMPERATURE',
            'POROSITY',
            'PEST',
            'EROSION/BURIAL']
        self.config = config
        self.later_inputs = {}
        self.raw = self.read_file(self.path)
        self.error_code = 0
        # Will only have 'restart' key if it is a restart.
        # Therefore, if KeyError, not a restart.
        self.config.setdefault('restart', False)
        for keyword in keyword_list:
            self.get_keyword_block(keyword)

        # Get keyword blocks that require unique handling due to format.
        self.get_initial_conditions_block()
        self.get_condition_blocks()
        self.get_minerals()
        self.get_isotope_block()
        self.get_flow()

        if config['aqueous_database'] is not None:
            self.aqueous_database = CrunchNameList(config['aqueous_database'])
        if config['catabolic_pathways'] is not None:
            self.catabolic_pathways = CrunchNameList(config['catabolic_pathways'])
        # Parse the thermodynamic database only where the config asks for it to be edited, and only
        # on a Template that will write one. Parsing is not free -- 60 ms and 2 MB a time, and a log
        # K recomputation is minutes -- and a later input file never writes a database of its own:
        # _print_aux_files writes the top-level InputFile's.
        database_sections = [
            key for key in ('database_parameters', 'database_logk', 'database_isotopes',
                            'database_regrid', 'database_add')
            if config.get(key)
        ]

        if config.get('parse_database', True) and database_sections:
            if config.get('database') is None:
                # Doing nothing would be the failure this whole feature exists to avoid: a config
                # that asks for something and is quietly ignored.
                raise ValueError(
                    f'ConfigError: {database_sections} need a \'database\' entry naming the .dbs '
                    f'file to edit.'
                )

            self.database = Database(config['database'])
            # Isotopes first, so the copies exist to be regridded and held to their parents; the
            # regrid next, because it rebuilds every gridded row and changes their width; the
            # recomputation last, since it edits tokens in place on whatever grid it finds.
            # Augmentation first: a species has to be in the database before it can be
            # labelled as an isotope, or regridded, or swept.
            self.add_species()
            reports = self.add_isotopes()
            self.regrid_database()
            self.recompute_log_k()
            # Last, because a recomputation copies each parent's column onto its copy to keep the
            # pair together, which would wipe an offset applied any earlier.
            self.apply_isotope_offsets(reports)

        # Check template is not a restart file to avoid infinite recursion.
        if not self.config['restart']:
            # Check for restarts.
            try:
                later_files = self.keyword_blocks['RUNTIME'].contents['later_inputfiles']
            except KeyError:
                return
            if later_files:
                print('*** Later input files found ***')
                for later_file in later_files:
                    try:
                        # The changes specified in the Omphalos config propagate unchanged down the
                        # chain. I.e. if we change a boundary condition we expect it to be the same
                        # in later restarts. To vary parameters between restarts instead, use a
                        # restart_chain config with the 'staged' parameter method, which supersedes
                        # this path (see configure_staged_input_files in generate_inputs.py).
                        later_config = copy.deepcopy(self.config)
                        later_config['template'] = later_file
                        # A later input file runs in the same directory against the same
                        # database, which the top-level InputFile writes. Parsing it again here
                        # would cost a copy per later file and, with database_logk, a full
                        # recomputation per later file, for a database nothing ever writes -- and
                        # re-applying the sweep to it would have nothing to apply the sweep to.
                        later_config['parse_database'] = False
                        later_config.pop('database_parameters', None)
                        later_config.pop('database_logk', None)
                        later_config.pop('database_isotopes', None)
                        later_config['restart'] = True
                        self.later_inputs.update({later_file: Template(later_config)})
                        print(f'*** IMPORTED LATER FILE {later_file} ***')
                    except FileNotFoundError:
                        import __main__
                        script_name = str(__main__.__file__).split('/')[-1]
                        if script_name == 'make_restarts.py':
                            return
                        else:
                            raise FileNotFoundError
            else:
                sys.exit('You have specified a restart without specifying which input file to run next. Exiting.')

    @staticmethod
    def read_file(path):
        """Return a dictionary of lines in a file, with the values as the line numbers.

        Will ignore any commented lines in the CT input file, but will still count their line number,
        so line numbers in dictionary will map to the true line number in the file. Comments are
        recognised wherever the '!' falls, so an indented comment is dropped like any other rather
        than being parsed as a block entry. The block parsers skip the resulting gaps.

        Lines continued with a trailing ampersand are joined onto the line they continue, so an entry
        broken across several lines is read as the single entry it represents.
        """
        input_file = {}

        with open(path, 'r') as f:
            for line_num, line in enumerate(f):
                # Input files edited on UNIX systems have newline characters that must be stripped.
                # Also strip any trailing whitespace.
                if line.lstrip().startswith('!'):
                    # It's a commented line, so don't import.
                    pass
                else:
                    input_file.update({line_num: line.rstrip('\n ')})

            f.close()

        return Template.join_continuations(input_file)

    @staticmethod
    def join_continuations(input_file):
        """Join lines continued with a trailing ampersand onto the line they continue.

        The manual allows long entries to be broken over several lines by ending each but the last
        with an ampersand, so the tokens belong to one entry. Read line by line they instead become a
        stray '&' token plus a bogus entry keyed on the continuation's first word, which then breaks
        anything that reads the values as numbers.

        The consumed lines are removed, leaving a gap. Line numbers are not renumbered, so the END
        statements the block parsers search for keep their positions, and those parsers already skip
        gaps left by comments.

        Args:
            input_file: Dictionary of lines keyed by line number.

        Returns:
            The same dictionary, with continuations joined.
        """
        line_nums = sorted(input_file)

        for i, line_num in enumerate(line_nums):
            if line_num not in input_file:
                # Already consumed as the continuation of an earlier line.
                continue

            next_index = i + 1
            while input_file[line_num].rstrip().endswith(CONTINUATION):
                # Skip over comment and blank gaps to find the line being continued onto.
                while next_index < len(line_nums) and line_nums[next_index] not in input_file:
                    next_index += 1

                trimmed = input_file[line_num].rstrip()[:-len(CONTINUATION)].rstrip()

                # A continuation marker with nothing to continue onto, or with the block's END next,
                # is malformed. Drop the marker rather than swallowing the END and losing the block.
                if next_index >= len(line_nums):
                    input_file[line_num] = trimmed
                    break
                continuation = input_file[line_nums[next_index]]
                if continuation.split() and continuation.split()[0].upper() == 'END':
                    input_file[line_num] = trimmed
                    break

                input_file[line_num] = f'{trimmed} {continuation.strip()}'
                del input_file[line_nums[next_index]]
                next_index += 1

        return input_file

    def block_line(self, line_num):
        """Return a line inside a keyword block, split into words, or [] if there is nothing to read.

        Comment lines are dropped by read_file but their line numbers are preserved, so the index has
        gaps where comments were; blank lines inside a block are legal CrunchTope input and carry no
        entry. Both are nothing to read, so callers skip them.
        """
        return self.raw.get(line_num, '').split()

    def add_isotopes(self):
        """Add the isotope systems the config asks for, before anything else touches the database.

        First, because everything downstream is written in terms of what the database holds: a
        ``database_parameters`` sweep can name an isotopologue, and a log K recomputation has to know
        the pairs exist. It cannot *recompute* them -- pyGCC holds no isotopologues -- so what it
        does instead is copy each parent's new column back onto its copy, which only works if the
        copies are already there. The config section is ``database_isotopes``, a list of systems.

        Each system reaches the aqueous kinetics namelist and the catabolic pathways as well as the
        .dbs, since a thermodynamic isotopologue with no reactions does nothing. Two keys are for
        those files: ``reaction_names`` for reaction names the formula rule cannot derive, and
        ``keq_offset`` for equilibrium fractionation. Kinetic fractionation is not set here -- it
        lives in the deck's AQUEOUS_KINETICS rates, which ``aqueous_kinetics:`` already sweeps.

        Returns:
            A list of IsotopeReports, empty where the config asks for none.
        """
        systems = self.config.get('database_isotopes')

        if not systems:
            return []

        if self.config.get('add_isotopes') is False:
            # rhea sets this on the per-run Templates it rebuilds from the run directories, whose
            # databases already carry the isotopes. Adding them again would find them present and
            # do nothing, but the check says so rather than relying on that.
            return []

        from omphalos.isotopes import add_isotope, add_isotope_reactions

        reports = []

        for system in systems:
            settings = dict(system)
            element = settings.pop('element')
            label = str(settings.pop('label'))
            reaction_names = settings.pop('reaction_names', None)
            keq_offset = settings.pop('keq_offset', None)
            logk_offset = settings.pop('logk_offset', None)

            print(f'*** Adding {element}{label} to the database ***')
            report = add_isotope(self.database, element, label, **settings)

            for namelist in (self.aqueous_database, self.catabolic_pathways):
                added, needs_name = add_isotope_reactions(
                    namelist, element, label, report.labelled,
                    names=reaction_names, keq_offset=keq_offset,
                )
                report.reactions.extend(added)
                report.reactions_needing_name.extend(needs_name)

            report.logk_offset = logk_offset
            print(report.summary())
            reports.append(report)

        return reports

    def apply_isotope_offsets(self, reports):
        """Impose equilibrium fractionation on the isotopologues, where the config asks for it.

        ``keq_offset`` reaches the namelist reactions; ``logk_offset`` reaches the database rows,
        which is where a mineral or secondary species keeps its equilibrium constant. Both are
        optional, and an isotope system with neither has no fractionation in it at all -- which is
        the point of copying log Ks unchanged.

        Args:
            reports: The IsotopeReports add_isotopes returned.

        Returns:
            {isotopologue: offset applied}, across every system.
        """
        from omphalos.isotopes import apply_logk_offset

        applied = {}

        for report in reports or []:
            offset = getattr(report, 'logk_offset', None)

            if offset is None:
                continue

            moved = apply_logk_offset(self.database, report.labelled, report.atoms, offset)
            applied.update(moved)

            print(f'*** Offset {len(moved)} {report.isotope} row(s) by {offset:+g} per atom ***')

        return applied

    def add_species(self):
        """Add species the database lacks, from a source compilation, where the config asks.

        The alternative to regenerating a database wholesale, which the plan's appendix argues
        against with measurements: a full pyGCC regeneration of `SukindaCr53.dbs` produces a third
        of the species and none of the custom ones, discarding exactly the fitted values pyGCC
        cannot compute. Adding the row a model is missing changes nothing else.

        The config section is ``database_add``, a mapping of section to species names, with
        ``on_unknown`` steering strictness and every other key passed to LogKCalculator.

        Returns:
            The Augmentation, or None where the config asks for nothing.
        """
        settings = self.config.get('database_add')

        if not settings:
            return None

        if self.config.get('recompute_log_k') is False:
            # rhea sets this on the per-run Templates it rebuilds from run directories, whose
            # databases already carry the added rows.
            return None

        from omphalos.logk import LogKCalculator

        settings = dict(settings)
        on_unknown = settings.pop('on_unknown', 'warn')
        sections = {
            key: settings.pop(key)
            for key in list(settings)
            if isinstance(settings[key], list)
        }

        if not sections:
            raise ValueError(
                "ConfigError: 'database_add' needs at least one section naming species to add, "
                "e.g. minerals: ['Anhydrite']."
            )

        print(f'*** Adding {sum(len(v) for v in sections.values())} species from the source '
              f'compilation ***')

        result = LogKCalculator(**settings).add_species(
            self.database, sections, on_unknown=on_unknown
        )
        print(result.summary())

        return result

    def regrid_database(self):
        """Rewrite the database onto a different set of temperature points, where the config asks.

        The usual eight points span 0-300 C, so a model that lives between 2 and 40 spends five of
        them on temperatures it never visits. A grid chosen for the problem is worth having, and it
        is also what makes a low pressure computable: pyGCC returns no value above 100 C at 1 bar,
        because the water there is steam.

        The config section is ``database_regrid``; ``temperatures`` is the new grid and ``reactions``
        steers which rows pyGCC is asked for, with every other key passed to LogKCalculator. Rows it
        cannot supply are resampled from the curve they already carry.

        Done once, on the template. Unlike a recomputation this is not a token edit -- changing the
        number of points changes the width of every row carrying a log K vector -- so it is not
        something to vary between runs of one sweep.

        Returns:
            The LogKRegrid, or None where the config asks for nothing.
        """
        settings = self.config.get('database_regrid')

        if not settings:
            return None

        if self.config.get('recompute_log_k') is False:
            # rhea sets this on the per-run Templates it rebuilds from the run directories, whose
            # databases are already on the new grid.
            return None

        from omphalos.logk import LogKCalculator

        settings = dict(settings)

        try:
            temperatures = settings.pop('temperatures')
        except KeyError:
            raise ValueError(
                "ConfigError: 'database_regrid' needs a 'temperatures' entry giving the new grid, "
                'in degrees Celsius.'
            ) from None

        reactions = settings.pop('reactions', 'all')

        print(f'*** Regridding the database onto {temperatures} ***')

        return LogKCalculator(**settings).regrid(
            self.database, temperatures, reactions=reactions
        )

    def recompute_log_k(self):
        """Recompute the database's log K columns with pyGCC, where the config asks for it.

        Done once, on the template, before any sweep, where every setting is fixed: the
        recomputation then depends only on the database and the method choices, so doing it per run
        would repeat a SUPCRT-style calculation per reaction for no gain. A ``database_parameters``
        sweep then edits the recomputed file, which is the intended order -- fitted values such as
        exchange coefficients and kinetic rates are ones pyGCC cannot compute and does not touch.

        Where a setting is *swept* -- a pressure series, most usefully -- there is no single answer
        to compute here, so the work is deferred to ``_apply_logk_recomputation``, once per run.

        The config section is ``database_logk``; ``reactions`` and ``on_unmatched`` steer coverage
        and strictness, and every other key is passed to LogKCalculator.

        Returns:
            The LogKRecalculation, or None where the config asks for nothing or defers it per run.
        """
        settings = self.config.get('database_logk')

        if not settings:
            return None

        if self.config.get('recompute_log_k') is False:
            # rhea sets this on the per-run Templates it rebuilds from the run directories. Those
            # databases have already been recomputed, and redoing it would repeat the whole
            # calculation for every run in the sweep.
            return None

        from omphalos.generate_inputs import split_logk_settings

        settings, swept = split_logk_settings(settings)

        if swept:
            # Handing LogKCalculator the specification itself -- ['custom', [1.0, 500.0]] as a
            # pressure -- is what would otherwise happen here, and it would not be caught.
            print(f'*** log K recomputation deferred per run: {sorted(swept)} swept ***')
            return None

        from omphalos.logk import LogKCalculator

        sections = settings.pop('sections', None)
        reactions = settings.pop('reactions', 'all')
        on_unmatched = settings.pop('on_unmatched', 'warn')

        print('*** Recomputing database log K columns with pyGCC ***')
        result = LogKCalculator(**settings).recompute(
            self.database, sections=sections, reactions=reactions, on_unmatched=on_unmatched
        )
        print(result.summary())

        return result

    def make_dict(self):
        """Returns a dict of InputFile objects, based on the Template."""
        file_dict = dict.fromkeys(np.arange(self.config['number_of_files']))
        for file in file_dict:
            # Whole InputFile must be a deep copy to avoid memory addressing problems associated with immutability of
            # string attributes.
            file_dict[file] = copy.deepcopy(InputFile(self.config['template'], self.keyword_blocks,
                                                      self.condition_blocks, self.aqueous_database,
                                                      self.catabolic_pathways, self.later_inputs,
                                                      self.database))
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
                # Commented and blank lines carry no entry, so skip them.
                line_list = self.block_line(a)
                if not line_list:
                    continue
                keyword_dict.update({block_entry_key(keyword, line_list): line_list[1:]})
            block.contents = keyword_dict
            self.keyword_blocks.update({keyword: block})
        except IndexError:
            print(
                f'The keyword "{keyword}" you searched for does not exist. If you are sure that this keyword is in '
                f'your input file, check your spelling.')

    def get_condition_blocks(self):
        """Special method for getting all CONDITION blocks from an input file, of which there may be multiple.

        Assigns each CONDITION block to a dictionary in the inputFile object specifically for geochemical conditions.
        The key for each dictionary entry is the condition name specified in the CrunchTope input file.
        """
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
                # Commented and blank lines carry no entry, so skip them.
                line_list = self.block_line(a)
                if not line_list:
                    continue
                keyword_dict.update({line_list[0]: line_list[1:]})

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
                # the dict key (in this specific context, the rare isotope).
                # Commented and blank lines carry no entry, so skip them.
                line_list = self.block_line(a)
                if not line_list:
                    continue
                try:
                    reordered_list = [line_list[0]] + line_list[2:]
                    keyword_dict.update({line_list[1]: reordered_list})
                except IndexError:
                    # The block keyword is by itself, so there is no rare isotope keyword to use as a key.
                    # This will raise an IndexError, so catch it and allocate
                    # the dict entries accordingly.
                    keyword_dict.update({line_list[0]: line_list[1:]})
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
                # Use the coordinate set as the dict key, since a condition may be applied over several
                # non-contiguous regions. Commented and blank lines carry no entry, so skip them.
                line_list = self.block_line(a)
                if not line_list:
                    continue
                try:
                    # Regex extracts keys as unique coordinate sets.
                    key = re.findall(r"\d+-\d+", self.raw[a])
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
            block.contents = keyword_dict
            self.keyword_blocks.update({keyword: block})
        except IndexError:
            print('The keyword "INITIAL_CONDITIONS" you searched for does not exist; check your input file for errors.')

    def get_flow(self):
        """Method to get the flow block from the input file and encode it as a KeywordBlock object in the InputFile.

        We have to do this in a separate method because the flow block has repeated entries to specify permeability
        and pressure over non-contiguous regions, so the left most word is not always unique. This means that the
        dictionary keys are overwriting each other.
        """
        # Get all instances of the keyword in question, in a numpy array.
        keyword = 'FLOW'
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
        zone_entries = {'permeability_x', 'permeability_y', 'permeability_z', 'pressure'}
        try:
            for a in np.arange(block_start[0], block_end[0]):
                # Entries that apply over a zone are keyed by their coordinate set, since the left most
                # word repeats. Commented and blank lines carry no entry, so skip them.
                line_list = self.block_line(a)
                if not line_list:
                    continue

                # Matched case insensitively, as CrunchTope reads these keywords. The exercises use
                # both spellings -- Ex10Flow2D writes 'permeability_y', Exercise18 writes
                # 'permeability_X' -- and comparing the raw token against a lowercase set silently
                # dropped every zone entry but the last for the capitalised form, which quietly
                # replaces a heterogeneous permeability field with a single value.
                if line_list[0].lower() in zone_entries and 'zone' in self.raw[a].lower():
                    try:
                        # Regex extracts keys as unique coordinate sets.
                        key = re.findall(r"\d+-\d+", self.raw[a])
                        key = ' '.join((line_list[0], ' '.join(key)))
                        # Check to see if the fix keyword has been invoked.
                        if line_list[-1] == 'fix':
                            entry = line_list[1:3] + [line_list[-1]]
                        else:
                            entry = line_list[1:3]
                        keyword_dict.update({key: entry})
                    except IndexError:
                        # The block keyword is by itself, so there is no coordinate to use as a key.
                        # This will raise an IndexError, so catch it and allocate
                        # the dict entries accordingly.
                        keyword_dict.update({line_list[0]: line_list[1:]})
                elif line_list[0] == 'pump':
                    try:
                        newpumpname = f'{line_list[0]}&{line_list[3]}&{line_list[4]}&{line_list[5]}'
                        keyword_dict.update({newpumpname: line_list[1:]})
                    except IndexError:
                        # Too few words to name the pump by its cell indices, so leave the entry out.
                        pass
                else:
                    keyword_dict.update({line_list[0]: line_list[1:]})

                block.contents = keyword_dict
                self.keyword_blocks.update({keyword: block})
        except IndexError:
            print('The keyword "FLOW" you searched for does not exist; check your input file for errors.')

    def get_minerals(self):
        """Method to get the MINERAL block from the input file and encode it as a KeywordBlock object in the InputFile.

        We have to do this in a separate method because the MINERAL block has to be able to specify parallel reactions for
        the same mineral (e.g. both a acidic and neutral mechanism for Forsterite dissolution). As a result, entries in the
        MINERAL block can have non-unique left most entries and can only be uniquely identifed through a combination of
        both the mineral name, and the `-label` entry referencing a specific kinetic rate law in the database. In this
        special keyword block method we create unique dictionary keys for each entry by appending the mineral name with its
        label entry, i.e. {mineral_name}_{label}. If there is no label entry, we take the label to be 'default', which is
        the same as the CrunchTope default.
        """
        # Get all instances of the keyword in question, in a numpy array.
        keyword = 'MINERALS'
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
                # Commented and blank lines carry no entry, so skip them.
                line_list = self.block_line(a)
                if not line_list:
                    continue
                # If keyword block title, don't modify.
                if line_list[0] == 'MINERALS':
                    new_min_name = 'MINERALS'
                else:
                    mineral_name = line_list[0]
                    # Look for -label keyword. If not found, then kinetics label is 'default'.
                    try:
                        label_index = line_list.index('-label')
                        kinetics_label = line_list[label_index + 1]
                    except ValueError:
                        kinetics_label = 'default'
                    new_min_name = f'{mineral_name}&{kinetics_label}'
                keyword_dict.update({new_min_name: line_list[1:]})
            block.contents = keyword_dict
            self.keyword_blocks.update({keyword: block})
        except IndexError:
            print('The keyword "MINERAL" you searched for does not exist; check your input file for errors.')
