"""Add an isotope of an element to a CrunchTope thermodynamic database.

An isotope system in a CrunchTope database is every species containing the element, duplicated under
a labelled name, with the reaction rewritten to use the labelled parent and the log Ks copied
unchanged. `SukindaCr53.dbs` carries three built this way by hand -- Ca44, S34 and Cr53 -- and this
module does the same mechanically.

The log Ks are copied rather than offset, so nothing here imposes a fractionation. Equilibrium
fractionation would be a small offset applied afterwards through Database.modify; kinetic
fractionation belongs in the aqueous kinetics database, which is where these models put it.

Two things make this safe to do mechanically.

**Which species are affected is decided by stoichiometry, not by name.** Calcite, Gypsum and
Dolomite all contain calcium with no 'Ca' in their names, so a name search would miss them. The test
is whether a reaction references a species already being labelled, applied over and over until the
set stops growing -- a CrunchTope reaction may be written on primary, secondary or gas species, and
`Cr(OH)3` is written on `Cr+++`, which is secondary, so the mineral is only reached on the second
pass, once `Cr+++` has itself been labelled.

**Names are formula-aware.** An element symbol is a capital letter and optional lowercase, so 'Ca'
counts as calcium only where the next character is not lowercase. That is what stops Calcite
becoming 'Ca44lcite', reads the C in 'Cl-' as chlorine rather than carbon, and the S in 'SiO2(aq)'
as silicon rather than sulfur. Checked against all 40 isotopologue names already in
`SukindaCr53.dbs`: the rule reproduces every one. Species whose names it declines -- the
trivially-named minerals -- are reported so a name can be given for them, never guessed at.

Substitution is aimed at particular tokens rather than run over the line, because a line holds text
that merely looks like a formula: `rate(25C)` in a kinetics block, and the trailing `'25C.data'` on
some mineral rows, would both be mangled by a carbon isotope otherwise.
"""

import re

from core.keyword_block import KEY_SEPARATOR
from omphalos.database import tokenise

# Where an isotope's rows are added, in the order they are written. Primary species come first
# because everything else is written in terms of them.
ISOTOPE_SECTIONS = (
    'primary_species',
    'secondary_species',
    'gases',
    'minerals',
    'surface_complexation',
    'exchange',
)


def isotope_name(name, element, label):
    """Return `name` with the element labelled everywhere it appears as a formula symbol.

    Args:
        name: A species or mineral name, e.g. 'CaCO3(aq)'.
        element: The element symbol, e.g. 'Ca'.
        label: The mass number, e.g. '44'.

    Returns:
        The labelled name, or None where no unambiguous label can be placed -- a trivial name like
        'Calcite', 'Cl-' asked about carbon, or a subscripted formula like 'Ca2Al2O5.8H2O' where the
        label would run into the subscript and give the unreadable 'Ca442Al2O5.8H2O'.
    """
    # (?![a-z]) is the whole trick: an element symbol is a capital and optional lowercase, so a
    # symbol followed by a lowercase letter is a different symbol, or an ordinary word. (?![0-9])
    # then refuses a subscript, where 'Ca' + '44' + '2' could not be read back apart.
    symbol = re.compile(f'{re.escape(element)}(?![a-z])')
    labellable = re.compile(f'{re.escape(element)}(?![a-z0-9])')

    if not labellable.search(name):
        return None

    # Every occurrence of the element has to be labellable, not just one, or the name comes back
    # half-labelled and means something else.
    if len(symbol.findall(name)) != len(labellable.findall(name)):
        return None

    return labellable.sub(f'{element}{label}', name)


class IsotopeReport:
    """What adding an isotope did, and what it could not do without being told."""

    def __init__(self, element, label):
        self.element = element
        self.label = label
        self.parents = []
        self.added = {}
        self.kinetics = []
        self.needs_name = {}
        self.already_present = []
        self.atoms = {}
        self.inferred_parents = False
        self.no_kinetics = []

    @property
    def isotope(self):
        return f'{self.element}{self.label}'

    @property
    def counts(self):
        return {
            'added': sum(len(names) for names in self.added.values()),
            'kinetics': len(self.kinetics),
            'needs_name': len(self.needs_name),
            'already_present': len(self.already_present),
        }

    def summary(self):
        lines = [f'{self.isotope}: {self.counts}']

        if self.inferred_parents:
            lines.append(
                f'  labelled primary species, inferred from their names -- CHECK THESE, a name is '
                f'not proof of composition: {self.parents}'
            )
        else:
            lines.append(f'  labelled primary species: {self.parents}')

        for section, names in self.added.items():
            lines.append(f'  {section}: {len(names)} added, e.g. {names[:4]}')

        if self.kinetics:
            lines.append(f'  mineral kinetics copied for: {self.kinetics}')

        if self.no_kinetics:
            lines.append(
                f'  WARNING: added with no mineral kinetics entry, because the parent has none '
                f'either. CrunchTope stops with "Kinetic mineral reaction not found in database" if '
                f'a deck names one of these, so give it a rate law by hand: {self.no_kinetics}'
            )

        if self.needs_name:
            lines.append(
                f'  NOT added, no formula name can be derived -- give one in `names`: '
                f'{sorted(self.needs_name)}'
            )

        if self.already_present:
            lines.append(f'  already in the database, left alone: {self.already_present}')

        return '\n'.join(lines)


def labelled_primaries(database, element, label, parents=None):
    """Return the primary species to be labelled, as {name: labelled name}.

    An element may have several primary species -- sulfur appears as `SO4--`, `HS-` and `S(aq)` in
    the databases here, one per redox state -- and all of them need labelling, or a species written
    in terms of the one that was missed has no isotopologue.

    Inference reads names, and a name is not proof of composition. Asked about sulfur, this also
    returns `CIS-12DCE`, where 'CIS' is the word cis in capitals rather than carbon, iodine and
    sulfur: no rule can tell those apart. Pass `parents` explicitly for anything that matters; the
    report says when the list was inferred so it can be checked.
    """
    if parents is None:
        candidates = list(database.primary_species)
    else:
        candidates = list(parents)
        missing = [name for name in candidates if name not in database.primary_species]

        if missing:
            raise KeyError(
                f'{missing} are not primary species of {database.path}, so they cannot be '
                f'labelled. Primary species are what every reaction is written in terms of.'
            )

    labelled = {}

    for name in candidates:
        new = isotope_name(name, element, label)

        if new is not None and new != name:
            labelled[name] = new

    if not labelled:
        raise ValueError(
            f"No primary species of {database.path} contains '{element}' as a formula symbol, so "
            f'there is nothing to label. Name the parents explicitly if they are spelled unusually.'
        )

    return labelled


def entries_by_name(database):
    """Return {name: (section, entry)} across every section an isotope touches."""
    found = {}

    for section in ISOTOPE_SECTIONS:
        for name, entry in getattr(database, section, {}).items():
            found.setdefault(name, (section, entry))

    return found


def required_species(database, labelled, wanted, parents):
    """Return the labelled species that have to be written, given what was asked for.

    A scope names what the caller wants labelled, but a species cannot be written unless everything
    its reaction references is written too: asking for `Chromite` alone would give a row referencing
    a `Cr53+++` that does not exist. So the scope is walked backwards through the reactions, pulling
    in whatever the requested species stand on. The parents are always required, since nothing can be
    written without them.
    """
    if wanted is None:
        return set(labelled)

    lookup = entries_by_name(database)
    required = set(parents)
    frontier = [name for name in wanted if name in labelled]
    required.update(frontier)

    while frontier:
        _, entry = lookup[frontier.pop()]
        reaction = getattr(entry, 'reaction', None)

        if reaction is None:
            continue

        for species in set(reaction.products) | set(reaction.reactants):
            if species in labelled and species not in required:
                required.add(species)
                frontier.append(species)

    return required


def close_over_reactions(database, element, label, labelled, atoms, wanted, names, report):
    """Extend the labelled set until nothing new references it, counting atoms as it goes.

    Labelling cannot stop at the primary species. A CrunchTope reaction may be written in terms of
    primary, secondary or gas species -- `Cr(OH)3` in SukindaCr53.dbs is written on `Cr+++`, which is
    secondary -- so the mineral is only reached once `Cr+++` itself has been labelled. Repeating
    until the set stops growing is what gets from `CrO4--` to `Cr53(OH)3`.

    The atom count comes out of the same walk: a species holds as many atoms of the element as its
    reaction's signed coefficients on already-labelled species say it does. `Cr2O7--`, written as
    two `CrO4--`, holds two.
    """
    growing = True

    while growing:
        growing = False

        for section in ISOTOPE_SECTIONS:
            if section == 'primary_species':
                continue

            for name, entry in getattr(database, section, {}).items():
                if name in labelled or name in report.needs_name:
                    continue

                reaction = getattr(entry, 'reaction', None)

                if reaction is None:
                    continue

                count = 0.0
                references = False

                for species, coefficient in reaction.products.items():
                    if species in labelled:
                        references = True
                        count += coefficient * atoms[species]

                for species, coefficient in reaction.reactants.items():
                    if species != name and species in labelled:
                        references = True
                        count -= coefficient * atoms[species]

                if not references:
                    continue

                new_name = names.get(name) or isotope_name(name, element, label)

                if new_name is None:
                    report.needs_name[name] = section
                    continue

                labelled[name] = new_name
                atoms[name] = count
                growing = True

    return labelled, atoms


def copy_weight(entry, new_name, weights, mass_shift, atoms):
    """Return the molecular weight text for a copy, or None to keep the parent's."""
    if 'weight' not in entry.parameters:
        return None

    if new_name in weights:
        return f'{weights[new_name]:g}'

    if mass_shift:
        return f'{entry.weight + mass_shift * atoms:.4f}'

    return None


def add_isotope(database, element, label, parents=None, species=None, names=None, weights=None,
                mass_shift=None, kinetics_from=None):
    """Add an isotope of an element to a database, in place.

    Args:
        database: The Database to add to. Rewritten and reparsed.
        element: The element symbol, e.g. 'Ca'.
        label: The mass number, e.g. '44'.
        parents: The primary species to label. Defaults to every primary species whose name carries
            the element as a formula symbol.
        species: Restrict the copies to these names, the parents excepted -- they are always
            labelled, since nothing else can be written without them. Worth using: a full
            compilation holds every calcium-bearing phase anyone has measured, and labelling all of
            them adds seventy rows to reach the handful a model needs. Default is everything.
        names: {existing name: isotopologue name}, for species the formula rule cannot name, and to
            override it where it can.
        weights: {isotopologue name: molecular weight}, for full control.
        kinetics_from: {isotopologue name: mineral name}, where a copy should take its rate law from
            a mineral other than its own parent. Needed where the parent has no kinetics entry: the
            ex9 sulfur model has hand-built `S32` and `S34` minerals with their own rates and none on
            the plain `S` they came from, so `{'S34': 'S32'}` is what gets S34 a rate law.
        mass_shift: Added to a copy's molecular weight for each atom of the element it contains, the
            atom count taken from its stoichiometry. `mass_shift=1` reproduces the Cr53 system in
            SukindaCr53.dbs exactly, where every weight is one unit above its parent's. Left unset,
            a copy keeps its parent's weight -- which is what that database does for S34, while Ca44
            was given the isotope's mass outright. Which is right is a modelling decision, so
            nothing is assumed.

    Returns:
        An IsotopeReport.
    """
    names = dict(names or {})
    weights = dict(weights or {})
    wanted = None if species is None else set(species)

    report = IsotopeReport(element, label)
    labelled = labelled_primaries(database, element, label, parents)
    report.parents = sorted(labelled)
    report.inferred_parents = parents is None

    # A primary species holds one atom of its own element, by construction.
    atoms = {name: 1.0 for name in labelled}

    labelled, atoms = close_over_reactions(
        database, element, label, labelled, atoms, wanted, names, report
    )
    report.atoms = atoms

    # The closure runs over the whole database; the scope is applied here, with whatever the
    # requested species depend on pulled in alongside them.
    required = required_species(database, labelled, wanted, labelled_primaries(
        database, element, label, parents))

    if wanted is not None:
        # Only report an unnameable species if it was actually asked for. Unscoped, the whole
        # database's trivially-named minerals are worth listing; scoped, they are noise.
        report.needs_name = {
            name: section for name, section in report.needs_name.items() if name in wanted
        }

    # Collected per section and inserted afterwards, because inserting moves every line below it.
    new_rows = {}

    for section in ISOTOPE_SECTIONS:
        entries = getattr(database, section, {})

        for name, entry in entries.items():
            if name not in labelled or name not in required:
                continue

            new_name = labelled[name]

            if new_name in entries:
                report.already_present.append(new_name)
                continue

            replacements = {0: requote(database, entry.line_index, 0, new_name)}

            for token in getattr(entry, 'reaction_tokens', []):
                referenced = database.raw_database[entry.line_index][token]

                if referenced in labelled:
                    replacements[token] = requote(database, entry.line_index, token,
                                                  labelled[referenced])

            weight = copy_weight(entry, new_name, weights, mass_shift, atoms.get(name, 0.0))

            if weight is not None:
                replacements[entry.parameters['weight'][1]] = weight

            new_rows.setdefault(section, []).append(
                (new_name, database.rewrite_tokens(entry.line_index, replacements))
            )

    kinetics = kinetics_copies(database, new_rows.get('minerals', []), names, element, label,
                               dict(kinetics_from or {}))
    report.kinetics = [name for name, _ in kinetics]

    # A mineral CrunchTope has no rate law for stops the run, and the message it gives points at the
    # deck rather than at the database, so it is worth saying here which ones lack one.
    copied = {name.split(KEY_SEPARATOR)[0] for name in report.kinetics}
    report.no_kinetics = sorted(
        name for name, _ in new_rows.get('minerals', []) if name not in copied
    )

    insert_rows(database, new_rows, kinetics)
    database.reparse()

    report.added = {section: [name for name, _ in rows] for section, rows in new_rows.items()}

    return report


def requote(database, line_index, token_index, new):
    """Return `new` quoted exactly as the token it replaces was.

    Species names are quoted in the row sections and bare in the mineral kinetics block, and a name
    that loses its quotes changes where the row's fields fall.
    """
    line = database.lines[line_index]
    _, start, end = tokenise(line)[token_index]

    return f"'{new}'" if line[start:end].startswith("'") else new


def kinetics_copies(database, minerals, names, element, label, kinetics_from):
    """Return (name, lines) for the mineral kinetics block of every mineral being added.

    A mineral with no kinetics entry has no rate, and CrunchTope stops with 'Kinetic mineral
    reaction not found in database'. The block is copied verbatim apart from the mineral's name:
    everything else in it -- the rate, the activation energy, `rate(25C)` -- is about the reaction,
    not the isotope, which is exactly what the hand-built systems in these databases do.
    """
    if 'mineral kinetics' not in database.sections:
        return []

    start, end = database.sections['mineral kinetics']
    copies = []

    for new_name, _ in minerals:
        source = kinetics_from.get(new_name) or unlabel(new_name, element, label, names)

        for key, entry in database.mineral_kinetics.items():
            if entry.name != source:
                continue

            block = database.lines[entry.line_index:block_end(database, entry, start, end)]
            renamed = [database.rewrite_tokens(
                entry.line_index,
                {0: requote(database, entry.line_index, 0, new_name)},
            )] + block[1:]
            copies.append((key.replace(source, new_name, 1), renamed))

    return copies


def unlabel(new_name, element, label, names):
    """Return the parent name a labelled name came from."""
    for parent, given in names.items():
        if given == new_name:
            return parent

    return new_name.replace(f'{element}{label}', element)


def block_end(database, entry, start, end):
    """Return the line index one past a mineral kinetics entry's block."""
    for line_index in range(entry.line_index + 1, end):
        line = database.lines[line_index]
        text = line.strip()

        # The next entry, or the separator before it, closes this one.
        if text.startswith('+--') or (line[:1].strip() and not text.startswith('&')):
            return line_index

    return end


def insert_rows(database, new_rows, kinetics):
    """Write the collected rows into the file, bottom-up so the line indices stay valid."""
    insertions = []

    for section, rows in new_rows.items():
        insertions.append((database.section_end(section), [line for _, line in rows]))

    if kinetics:
        separator = kinetics_separator(database)
        lines = []

        # Each block is followed by a separator, not preceded by one. CrunchTope reads this section
        # by scanning forward for the next line starting '+' (BreakFind), and the section already
        # ends with one, so a block appended after it must leave another behind -- otherwise the
        # scan past the last entry runs to end of file and CrunchTope dies reading the database.
        for _, block in kinetics:
            lines.extend(block + [separator])

        insertions.append((database.section_end('mineral_kinetics'), lines))

    for line_index, lines in sorted(insertions, reverse=True):
        database.insert_lines(line_index, lines)


def kinetics_separator(database):
    """Return the '+---' separator line the database's kinetics block uses, terminator included."""
    start, end = database.sections['mineral kinetics']

    for line_index in range(start, end):
        if database.lines[line_index].strip().startswith('+--'):
            return database.lines[line_index]

    return '+----------------------------------------------------\n'
