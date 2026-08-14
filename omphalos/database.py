"""Database parsing and surgical editing for CrunchTope.

A CrunchTope thermodynamic database (.dbs) mixes tokenised species rows with `key = value` kinetics
blocks, and CrunchTope will happily read a malformed one, so this module never re-prints from the
parsed objects. It keeps the file verbatim in `lines` and records, for every editable parameter, the
(line index, token index) it occupies. `modify` rewrites exactly that one token, so whitespace,
column alignment and trailing comments survive an edit, and an unedited round trip is byte-identical.

Row layouts are as read by CrunchTope's database.F90 and read_exchange.F90:

    primary                 name, dh_size, charge, weight
    secondary               name, n, (stoich, species) * n, log K * ntemp, dh_size, charge, weight
    gases                   name, molar_volume, n, (stoich, species) * n, log K * ntemp, weight
    minerals                name, molar_volume, n, (stoich, species) * n, log K * ntemp, weight
    surface complexation    name, n, (stoich, species) * n, log K * ntemp
    exchange                name, n, (stoich, species) * n, log K, bfit

Every log K slice is therefore taken from the front of the row, counting `temp_points` values past
the reaction, rather than from the back: the trailing field count varies by section and secondary
species carry an extra Bdot column when the database was written with one.
"""

import copy
import re
import warnings

from core.keyword_block import KEY_SEPARATOR, resolve_entry

# A token is a single-quoted string, which may contain spaces ('Debye-Huckel adh'), or a run of
# anything that is neither whitespace nor a comma. Fortran list-directed input, which is what
# CrunchTope reads these files with, accepts a comma as a value separator, and at least one row in
# the shipped databases uses them -- PlagAn5Or5 writes its log K columns as '4.49446, 3.80318, …'.
# Treating the comma as part of the token left those values as unparsed strings.
# Anything from an unquoted '!' onwards is a comment.
TOKEN_PATTERN = re.compile(r"'[^']*'|[^\s,]+")

# Names as they appear in Begin/End markers, mapped to the attribute they populate.
SECTION_ATTRIBUTES = {
    'primary': 'primary_species',
    'secondary': 'secondary_species',
    'gases': 'gases',
    'minerals': 'minerals',
    'surface complexation': 'surface_complexation',
    'aqueous kinetics': 'aqueous_kinetics',
    'mineral kinetics': 'mineral_kinetics',
    'exchange': 'exchange',
    'surface complexation parameters': 'surface_complexation_parameters',
}

# The four leading sections have no Begin marker; they simply follow the header in this order.
IMPLICIT_SECTIONS = ('primary', 'secondary', 'gases', 'minerals')

HEADER_LINES = 4

# Distinguishes parallel mineral kinetics rate laws that share a label, as 'Fe(OH)3&default#1'.
PARALLEL_SEPARATOR = '#'


def line_number(line_index):
    """Return the 1-based line number a 0-based index refers to, for messages a user has to act on."""
    return line_index + 1


def tokenise(line, offset=0):
    """Split a database line into tokens, dropping the line terminator and any trailing comment.

    Args:
        line: The verbatim line, terminator included.
        offset: Added to the returned spans, for tokenising part of a line.

    Returns:
        A list of (value, start, end) triples. `value` is a float where the token is an unquoted
        number and a string otherwise, with any surrounding quotes removed; `start` and `end` are
        character offsets into the line, so a caller can rewrite one token in place.
    """
    tokens = []

    for match in TOKEN_PATTERN.finditer(line.rstrip('\r\n')):
        text = match.group()

        if text.startswith('!'):
            break

        if text.startswith("'"):
            # Quoted tokens are always names, never numbers.
            value = text.strip("'")
        else:
            try:
                value = float(text)
            except ValueError:
                value = text

        tokens.append((value, match.start() + offset, match.end() + offset))

    return tokens


def values(tokens):
    """Return just the values from a tokenised line."""
    return [value for value, _, _ in tokens]


def marker(line):
    """Return the leading name on a line, unquoted, or '' for a blank line.

    Section markers are written both quoted ("'End of primary'") and bare ("Begin exchange"), and
    the quoted ones are followed by filler columns that CrunchTope reads and discards.
    """
    text = line.strip()

    if text.startswith("'"):
        closing = text.find("'", 1)
        if closing == -1:
            return ''
        return text[1:closing].strip()

    return text


def section_name(marker_text, keyword):
    """Return the section a Begin/End marker names, or None if it is not such a marker."""
    prefix = f'{keyword} '.lower()

    if not marker_text.lower().startswith(prefix):
        return None

    name = marker_text[len(prefix):].strip().lower()

    # 'End of minerals' and 'End surface complexation parameters' are both spellings in use.
    if keyword == 'End' and name.startswith('of '):
        name = name[3:].strip()

    return name


class Database:
    """A CrunchTope thermodynamic database, parsed and editable a token at a time."""

    def __init__(self, path):
        # Databases are almost always written on Windows and carry CRLF terminators. Read with
        # newline='' so the terminators survive verbatim in self.lines, which is what print() emits.
        with open(path, 'r', newline='') as file:
            lines = file.readlines()

        self.parse(path, lines)

    def parse(self, path, lines):
        """Build the whole object from the file's lines."""
        self.path = path
        self.lines = lines
        self.sections = {}
        self.index = {}
        self.duplicates = {}
        self.primary_species = {}
        self.secondary_species = {}
        self.gases = {}
        self.minerals = {}
        self.surface_complexation = {}
        self.aqueous_kinetics = {}
        self.mineral_kinetics = {}
        self.exchange = {}
        self.surface_complexation_parameters = {}

        self.raw_database = [values(tokenise(line)) for line in self.lines]

        # The header format is fixed, so line and column positions can be relied on -- but only
        # once it has been confirmed to be a header. Everything downstream slices rows against
        # temp_points, so a file that starts with anything else has to say so here rather than
        # fail with an IndexError from somewhere deeper.
        self.temp_points, self.temp_field = self.read_header()
        self.dh_params = self.raw_database[1:HEADER_LINES]

        self.sections = self.find_sections()
        self.parse_sections()

    def read_header(self):
        """Read the temperature grid from the first line.

        Returns:
            A (count, temperatures) pair.

        Raises:
            ValueError: If the first line is not a temperature-points row, or if the count it
                declares disagrees with the temperatures it lists. Both would otherwise mis-slice
                every log K in the file without complaint.
        """
        if len(self.raw_database) < HEADER_LINES:
            raise ValueError(
                f'{self.path} has {len(self.raw_database)} lines; a database begins with a '
                f"'temperature points' row and three Debye-Huckel rows."
            )

        header = self.raw_database[0]

        if len(header) < 2 or not str(header[0]).lower().startswith('temperature'):
            raise ValueError(
                f"{self.path} does not begin with a 'temperature points' row -- line 1 reads "
                f'{self.lines[0].strip()!r}. CrunchTope reads the grid from the first line, so '
                f'nothing may precede it, comments included.'
            )

        try:
            count = int(header[1])
        except (TypeError, ValueError) as error:
            raise ValueError(
                f'{self.path} line 1 does not give a temperature point count: {header[1]!r}.'
            ) from error

        temperatures = header[2:]

        if len(temperatures) != count:
            raise ValueError(
                f'{self.path} line 1 declares {count} temperature points but lists '
                f'{len(temperatures)}: {temperatures}.'
            )

        return count, temperatures

    def find_sections(self):
        """Locate each section by its Begin/End markers.

        Returns:
            A dictionary of section name to the (first, last) line indices of its contents, the
            markers themselves excluded.

        Databases differ in which sections they carry — an in-database 'aqueous kinetics' block is
        present in some and absent in others — so sections are found by name rather than by counting
        delimiters, which silently folded one section into the next when a database held an extra.
        """
        sections = {}
        start = HEADER_LINES
        open_block = None
        opened_at = None

        for line_index, line in enumerate(self.lines):
            text = marker(line)
            begun = section_name(text, 'Begin')

            if begun is not None:
                if open_block is not None:
                    raise ValueError(
                        f"{self.path} line {line_number(line_index)} begins '{begun}' while "
                        f"'{open_block}' is still open from line {line_number(opened_at)}."
                    )

                open_block, opened_at = begun, line_index
                start = line_index + 1
                continue

            name = section_name(text, 'End')

            if name is None:
                continue

            # A block closed by the wrong name means the section map is wrong from here on, and an
            # edit would then rewrite rows in a section the caller did not name.
            if open_block is not None and name != open_block:
                raise ValueError(
                    f"{self.path} line {line_number(line_index)} ends '{name}', but the open "
                    f"block is '{open_block}' from line {line_number(opened_at)}."
                )

            # The implicit sections have no Begin marker; their contents simply run from the end of
            # the header, or of the previous section, up to their own End marker.
            if name in SECTION_ATTRIBUTES:
                sections[name] = (start, line_index)

            open_block, opened_at = None, None
            start = line_index + 1

        if open_block is not None:
            raise ValueError(
                f"{self.path} never closes '{open_block}', begun at line "
                f'{line_number(opened_at)}.'
            )

        return sections

    def parse_sections(self):
        """Populate one attribute and one edit index entry per section."""
        block_parsers = {
            'mineral kinetics': self.parse_mineral_kinetics,
            'aqueous kinetics': self.parse_aqueous_kinetics,
        }

        entry_classes = {
            'primary': Species,
            'secondary': SecondarySpecies,
            'gases': Gas,
            'minerals': Mineral,
            'surface complexation': SurfaceComplex,
            'surface complexation parameters': SurfaceComplexationParameter,
            'exchange': ExchangeSpecies,
        }

        for name, (start, end) in self.sections.items():
            attribute = SECTION_ATTRIBUTES[name]

            if name in entry_classes:
                entries = self.parse_rows(start, end, entry_classes[name])
            else:
                entries = block_parsers[name](start, end)

            setattr(self, attribute, entries)
            self.index[attribute] = {
                key: entry.parameters for key, entry in entries.items()
            }

    def parse_rows(self, start, end, entry_class):
        """Parse a section written one entry per line.

        Where a name appears more than once — Goethite, Safflorite and UO2(s) all do in the
        databases shipped with CrunchTope — the first row wins, because that is the one CrunchTope
        uses: it scans the section forward and stops at the first match (database.F90). Keeping the
        last would edit a row the simulation never reads.
        """
        entries = {}

        for line_index in range(start, end):
            tokens = tokenise(self.lines[line_index])

            if not tokens:
                continue

            entry = entry_class(tokens, line_index, self.temp_points)

            if entry.name in entries:
                self.duplicates.setdefault(entry.name, []).append(line_index)
                continue

            entries[entry.name] = entry

        return entries

    def parse_mineral_kinetics(self, start, end):
        """Parse the mineral kinetics section.

        The format is unlike the species rows: '+---' separators, then a mineral name on its own
        line followed by indented `label = value` lines, optional Fortran namelist stanzas, and a
        `dependence` list that may continue over the following line. Entries are keyed
        'Mineral&label' so that a mineral carrying several rate laws keeps all of them, matching the
        composite keys used for repeatable keywords in core.keyword_block.
        """
        entries = []
        entry = None

        for line_index in range(start, end):
            line = self.lines[line_index]
            text = line.strip()

            if not text or text.startswith('+--'):
                continue

            tokens = tokenise(line)

            if not tokens:
                # A comment-only line.
                continue

            if line[:1].strip() and not text.startswith('&'):
                # An unindented, non-namelist line names a new mineral.
                entry = MineralKinetics(tokens[0][0], line_index)
                entries.append(entry)
                continue

            if entry is None:
                continue

            if text.startswith('&'):
                entry.namelists.append(line_index)
                continue

            entry.add_attribute(line, line_index)

        # Key only once every label is known; the label line follows the mineral name.
        return self.key_kinetics(entries)

    @staticmethod
    def key_kinetics(entries):
        """Key mineral kinetics entries, keeping parallel reactions apart.

        A mineral repeated in this block is not a duplicate to discard: read_minkin.F90 loads it as
        an additional *parallel* rate law, and CrunchTope runs all of them. Distinct labels already
        give distinct keys -- CalciteRifle carries three -- but two blocks may share a label, and
        keeping only one of those would let an edit rewrite one rate law while the simulation runs
        two. Colliding keys are suffixed '#1', '#2', so both survive and neither can be reached by
        accident: naming the mineral, or the bare 'Mineral&label', matches several and raises.
        """
        by_key = {}

        for entry in entries:
            by_key.setdefault(entry.key, []).append(entry)

        keyed = {}

        for key, parallel in by_key.items():
            if len(parallel) == 1:
                keyed[key] = parallel[0]
                continue

            for number, entry in enumerate(parallel, start=1):
                keyed[f'{key}{PARALLEL_SEPARATOR}{number}'] = entry

        return keyed

    def parse_aqueous_kinetics(self, start, end):
        """Record the in-database aqueous kinetics section by entry name.

        This block is deprecated: the manual has aqueous kinetics in a separate namelist file named
        by the RUNTIME 'kinetic_database'/'aqueousdatabase' keyword, which omphalos/namelist.py
        handles and which is where a sweep should reach them. Legacy databases still carry the old
        block, though, and it has to be recognised -- otherwise the section that follows it absorbs
        it, which is what used to happen to mineral kinetics.

        Entries here run over several lines with no consistent continuation marker, and none of
        their parameters is editable through this module, so each is stored as the block of lines it
        occupies rather than being taken apart. A new entry starts on an unindented line whose first
        token is not a number.
        """
        entries = {}
        entry = None

        for line_index in range(start, end):
            line = self.lines[line_index]

            if not line.strip():
                continue

            tokens = tokenise(line)

            if line[:1].strip() and isinstance(tokens[0][0], str):
                entry = AqueousKinetics(tokens[0][0], line_index)
                entries[entry.name] = entry
            elif entry is not None:
                entry.lines.append(line_index)

        return entries

    def __deepcopy__(self, memo):
        """Copy only what an edit can change.

        Template.make_dict deep-copies an InputFile per run, and a database holds several thousand
        parsed species objects — order a gigabyte across a hundred runs if each were copied whole.
        Only `lines` and `raw_database` are written by modify(), and both are written by replacing
        whole elements rather than mutating them, so a shallow copy of each is enough and the parse
        is shared.
        """
        duplicate = self.__class__.__new__(self.__class__)
        memo[id(self)] = duplicate
        duplicate.__dict__.update(self.__dict__)
        duplicate.lines = list(self.lines)
        duplicate.raw_database = list(self.raw_database)

        return duplicate

    def __getstate__(self):
        """Pickle the file, not the parse.

        A parsed database is a couple of megabytes of objects and one is recorded per run, so
        pickling it whole would add hundreds of megabytes to the input record of a hundred-run
        sweep. The lines are all an edit changes, and the parse rebuilds from them.
        """
        return {'path': self.path, 'lines': self.lines}

    def __setstate__(self, state):
        self.parse(state['path'], state['lines'])

    def locate(self, section, entry, parameter):
        """Resolve a config's (section, entry, parameter) to the tokens it names.

        Returns:
            A (key, line_index, token_indices, scalar) tuple. token_indices is always a list;
            scalar says whether the parameter occupies a single token, which is a property of the
            parameter rather than of how many temperature points this database happens to have.

        Raises:
            KeyError: If the section, entry or parameter is not in the database. Failing here is
                deliberate: an unrecognised name would otherwise leave the database unedited and the
                sweep would run every case against identical input.
        """
        if section not in self.index:
            raise KeyError(
                f"'{section}' is not a section of {self.path}. Available: {sorted(self.index)}"
            )

        entries = self.index[section]

        try:
            key = resolve_entry(entries, entry)
        except KeyError as error:
            # resolve_entry raises KeyError(entry) when nothing matches and a KeyError carrying an
            # explanation when a bare name is ambiguous. Only the first wants rewording.
            if str(error) != repr(entry):
                raise

            # A mineral whose parallel rate laws share a label is keyed 'Mineral&label#1',
            # 'Mineral&label#2', so the label alone matches nothing. Say which to name.
            parallel = sorted(
                key for key in entries if key.startswith(f'{entry}{PARALLEL_SEPARATOR}')
            )

            if parallel:
                raise KeyError(
                    f"'{entry}' names {len(parallel)} parallel rate laws in '{section}', which "
                    f'CrunchTope runs together. Say which one you mean: {parallel}.'
                ) from error

            raise KeyError(
                f"'{entry}' is not in the '{section}' section of {self.path}."
            ) from error

        parameters = entries[key]

        if parameter not in parameters:
            raise KeyError(
                f"'{parameter}' is not an editable parameter of '{key}' in section '{section}'. "
                f"Available: {sorted(parameters)}"
            )

        line_index, token_indices = parameters[parameter]
        scalar = isinstance(token_indices, int)

        if scalar:
            token_indices = [token_indices]

        return key, line_index, list(token_indices), scalar

    def value(self, section, entry, parameter):
        """Return a parameter's current value, read back out of the lines.

        A parameter that occupies one token comes back as a number, and one that spans a vector
        comes back as a list -- including a one-element list where the database has a single
        temperature point. The shape follows the parameter, not the database, so a recorded sweep
        has the same form whatever grid the database was written on.
        """
        _, line_index, token_indices, scalar = self.locate(section, entry, parameter)
        tokens = tokenise(self.lines[line_index])
        found = [tokens[index][0] for index in token_indices]

        return found[0] if scalar else found

    def modify(self, section, entry, parameter, value):
        """Rewrite one parameter in place.

        Args:
            section: The section attribute name, e.g. 'exchange' or 'mineral_kinetics'.
            entry: The entry within it, e.g. 'CaXRifle'. A mineral kinetics entry may be named
                bare ('Calcite') while only one rate law exists for it.
            parameter: The parameter to change, e.g. 'log_k'.
            value: The new value. A scalar given for a parameter spanning several tokens, such as a
                log K vector over the temperature points, is written to every one of them.

        Raises:
            KeyError: If the section, entry or parameter is not in the database. Failing here is
                deliberate: an unrecognised name would otherwise leave the database unedited and the
                sweep would run every case against identical input.
            ValueError: If a sequence is given whose length does not match the parameter.
        """
        key, line_index, token_indices, _ = self.locate(section, entry, parameter)

        if key in self.duplicates:
            # The duplicates shipped with CrunchTope are exact copies, so the edited row is the one
            # that counts, but the file is left disagreeing with itself and that is worth saying.
            warnings.warn(
                f"'{key}' appears more than once in section '{section}'. Editing the row "
                f'CrunchTope reads (line {line_number(line_index)}); the copies at lines '
                f'{[line_number(index) for index in self.duplicates[key]]} keep their old values.'
            )

        if isinstance(value, (str, bytes)) or not hasattr(value, '__len__'):
            new_values = [value] * len(token_indices)
        else:
            new_values = list(value)

        if len(new_values) != len(token_indices):
            raise ValueError(
                f"'{parameter}' of '{key}' spans {len(token_indices)} values, but "
                f'{len(new_values)} were given.'
            )

        for token_index, new_value in zip(token_indices, new_values):
            self.set_token(line_index, token_index, new_value)

        self.refresh(section, key, parameter)

    def refresh(self, section, key, parameter):
        """Bring the parsed view of one entry back into step with the lines.

        The parsed objects are shared between the copies Template.make_dict hands out -- that is
        what keeps a hundred-run sweep from costing a gigabyte -- so an edit cannot write into them
        without changing what every other run sees. The entry and its section dict are therefore
        copied first, and only this database's copy is updated. Reading
        ``database.minerals['Calcite'].log_k`` after an edit then gives this run's value rather
        than the template's.
        """
        entries = dict(getattr(self, section))
        entry = copy.copy(entries[key])
        current = self.value(section, key, parameter)

        if hasattr(entry, 'attributes'):
            # Mineral kinetics keeps its values in a dict, under CrunchTope's own spellings.
            entry.attributes = dict(entry.attributes)
            entry.attributes[parameter] = current

            if parameter == 'label':
                entry.label = current
        else:
            # Row parameters are named exactly as the attribute that holds them.
            setattr(entry, parameter, current)

        entries[key] = entry
        setattr(self, section, entries)

    def set_token(self, line_index, token_index, value):
        """Replace a single token, preserving the column it occupies where the new text is shorter."""
        line = self.lines[line_index]
        tokens = tokenise(line)
        _, start, end = tokens[token_index]

        text = value if isinstance(value, str) else repr(float(value))
        text = text.rjust(end - start)

        self.lines[line_index] = line[:start] + text + line[end:]
        self.raw_database[line_index] = values(tokenise(self.lines[line_index]))

    def replace_tokens(self, line_index, first, last, texts):
        """Replace a run of tokens with a different run, which may be a different length.

        Everything outside the replaced span is kept exactly: the species name and reaction before
        it, the molecular weight, trailing fields and comment after it, and the line terminator.
        This is what changing the temperature grid needs, since that changes how many log K columns
        every row carries -- unlike modify(), which only ever rewrites a token in place.

        Args:
            line_index: The line to rewrite.
            first: Index of the first token to replace.
            last: Index one past the last token to replace.
            texts: The replacement tokens, already formatted.
        """
        line = self.lines[line_index]
        tokens = tokenise(line)
        start = tokens[first][1]
        end = tokens[last - 1][2]

        self.lines[line_index] = line[:start] + ''.join(texts) + line[end:]
        self.raw_database[line_index] = values(tokenise(self.lines[line_index]))

    def reparse(self):
        """Rebuild the parse from the current lines, after the row layout has changed."""
        self.parse(self.path, self.lines)

    def print(self, path):
        """Write the database out verbatim.

        Only tokens touched by modify() differ from the file that was read, so an unedited round
        trip is byte-identical, comments, alignment and line terminators included.
        """
        with open(path, 'w', newline='') as file:
            file.writelines(self.lines)


class Species:
    """A primary species: name, Debye-Huckel size, charge and molecular weight."""

    def __init__(self, tokens, line_index, temp_points=None):
        entry = values(tokens)
        self.line_index = line_index
        self.name = entry[0]
        self.dh_size = entry[1]
        self.charge = entry[2]
        self.weight = entry[3]
        self.parameters = {
            'dh_size': (line_index, 1),
            'charge': (line_index, 2),
            'weight': (line_index, 3),
        }


class ReactingSpecies(Species):
    """A species written as a reaction plus a log K at each temperature point.

    Subclasses set `name_columns`, the number of columns before the reacting species count, and
    inherit the front-counted log K slice.
    """

    name_columns = 1

    def __init__(self, tokens, line_index, temp_points):
        entry = values(tokens)
        self.line_index = line_index
        self.name = entry[0]
        self.reaction_species_count = int(entry[self.name_columns])

        reaction_start = self.name_columns + 1
        reaction_end = reaction_start + (self.reaction_species_count * 2)
        log_k_end = reaction_end + temp_points

        self.reaction = Reaction(self.name, entry[reaction_start:reaction_end])
        self.log_k = entry[reaction_end:log_k_end]
        self.parameters = {'log_k': (line_index, list(range(reaction_end, log_k_end)))}

        self.read_trailing(entry, log_k_end, line_index)

    def read_trailing(self, entry, first, line_index):
        """Read whatever follows the log K columns. Sections differ in what that is."""


class SecondarySpecies(ReactingSpecies):
    """An aqueous complex: log K columns are followed by size, charge and weight."""

    def read_trailing(self, entry, first, line_index):
        self.dh_size = entry[first]
        self.charge = entry[first + 1]
        self.weight = entry[first + 2]
        self.parameters.update({
            'dh_size': (line_index, first),
            'charge': (line_index, first + 1),
            'weight': (line_index, first + 2),
        })


class Gas(ReactingSpecies):
    """A gas: a molar volume before the reaction, and a molecular weight after the log K columns."""

    name_columns = 2

    def __init__(self, tokens, line_index, temp_points):
        self.molar_volume = values(tokens)[1]
        super().__init__(tokens, line_index, temp_points)
        self.parameters['molar_volume'] = (line_index, 1)

    def read_trailing(self, entry, first, line_index):
        self.weight = entry[first]
        self.parameters['weight'] = (line_index, first)


class Mineral(Gas):
    """A mineral. Identical in layout to a gas."""

    rate_laws = frozenset(
        {'tst', 'monod', 'irreversible', 'PrecipitationOnly', 'DissolutionOnly', 'MonodBiomass'}
    )


class SurfaceComplex(ReactingSpecies):
    """A surface complex: a reaction and log K columns, with nothing after them."""


class ExchangeSpecies(ReactingSpecies):
    """An ion exchange species.

    CrunchTope reads these as `name, n, (stoich, species) * n, log K, bfit` (read_exchange.F90), so
    the selectivity coefficient is a single value, not a vector over temperature. This is the
    parameter PEST is used to fit and the reason database editing exists.
    """

    def __init__(self, tokens, line_index, temp_points):
        # The log K here is one value regardless of how many temperature points the database has.
        super().__init__(tokens, line_index, 1)

    def read_trailing(self, entry, first, line_index):
        log_k_index = first - 1
        self.log_k = entry[log_k_index]
        self.bfit = entry[first]
        self.parameters.update({
            'log_k': (line_index, log_k_index),
            'bfit': (line_index, first),
        })


class SurfaceComplexationParameter:
    """A surface site and its charge, from the surface complexation parameters section."""

    def __init__(self, tokens, line_index, temp_points=None):
        entry = values(tokens)
        self.line_index = line_index
        self.name = entry[0]
        self.charge = entry[1]
        self.parameters = {'charge': (line_index, 1)}


class MineralKinetics:
    """One rate law for one mineral, from the mineral kinetics section.

    Attributes are the `key = value` lines under the mineral name — label, type, rate(25C),
    activation and dependence — and are indexed by the CrunchTope spelling, so a config names
    'rate(25C)' exactly as the database does.
    """

    def __init__(self, name, line_index):
        self.name = name
        self.line_index = line_index
        self.label = 'default'
        self.attributes = {}
        self.namelists = []
        self.parameters = {}

    @property
    def key(self):
        return f'{self.name}{KEY_SEPARATOR}{self.label}'

    def add_attribute(self, line, line_index):
        """Record one `key = value` or `key : value` line."""
        tokens = tokenise(line)

        if not tokens:
            return

        first = tokens[0][0]

        if not isinstance(first, str):
            # A dependence list continued onto its own line.
            return

        if len(tokens) > 1 and tokens[1][0] in ('=', ':'):
            key, value_index = first, 2
        elif first.endswith(('=', ':')):
            key, value_index = first[:-1], 1
        else:
            return

        if value_index >= len(tokens):
            self.attributes[key] = None
            return

        value = tokens[value_index][0]
        self.attributes[key] = value
        self.parameters[key] = (line_index, value_index)

        if key == 'label':
            self.label = value

    @property
    def type(self):
        return self.attributes.get('type')

    @property
    def rate(self):
        return self.attributes.get('rate(25C)')

    @property
    def activation(self):
        return self.attributes.get('activation')


class AqueousKinetics:
    """An aqueous kinetics entry, held as the lines it occupies. Not editable through modify()."""

    def __init__(self, name, line_index):
        self.name = name
        self.line_index = line_index
        self.lines = [line_index]
        self.parameters = {}


class Reaction:
    """The reaction a secondary species, gas, mineral or exchange species is written as.

    All CT databases are written in terms of the breakdown of the secondary species (/mineral/gas).
    Therefore, negative stoichiometric coefficient indicates a reactant and positive indicates a
    product. Reaction datastruct contains two dicts, one for products and one for reactants.
    """

    def __init__(self, species_name, reaction_array):
        # Check to make sure reaction_array is even.
        if len(reaction_array) % 2 == 1:
            raise Exception(
                "Unpaired stoichiometric coefficient/species name in {} database entry".format(
                    species_name
                )
            )

        self.products = {}
        self.reactants = {species_name: 1.0}

        for i in range(int(len(reaction_array) / 2)):
            index = i * 2
            if reaction_array[index] == 0:
                raise Exception(
                    "Stoichiometric coefficient = 0 in {} database entry".format(species_name)
                )
            elif reaction_array[index] > 0:
                # Product.
                self.products.update({reaction_array[index + 1]: reaction_array[index]})
            elif reaction_array[index] < 0:
                # Reactant. Multiply by -1 to flip sign on reactant so we don't imply negative
                # reactant.
                self.reactants.update({reaction_array[index + 1]: (reaction_array[index] * -1)})
