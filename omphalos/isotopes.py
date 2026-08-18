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

# Standard atomic weights, used only to work out how much heavier an isotope is than the element it
# replaces: the default mass shift is the label minus the rounded weight below. Rounding a
# natural-abundance average is not always the most abundant isotope's mass number -- copper averages
# 63.55 while 63-Cu is the common one, and nickel, zinc and tellurium are the same -- so for those,
# set `mass_shift` explicitly rather than trusting the default.
ATOMIC_WEIGHTS = {
    'H': 1.008, 'He': 4.003, 'Li': 6.94, 'Be': 9.012, 'B': 10.81, 'C': 12.011, 'N': 14.007,
    'O': 15.999, 'F': 18.998, 'Ne': 20.180, 'Na': 22.990, 'Mg': 24.305, 'Al': 26.982,
    'Si': 28.085, 'P': 30.974, 'S': 32.06, 'Cl': 35.45, 'Ar': 39.95, 'K': 39.098, 'Ca': 40.078,
    'Sc': 44.956, 'Ti': 47.867, 'V': 50.942, 'Cr': 51.996, 'Mn': 54.938, 'Fe': 55.845,
    'Co': 58.933, 'Ni': 58.693, 'Cu': 63.546, 'Zn': 65.38, 'Ga': 69.723, 'Ge': 72.630,
    'As': 74.922, 'Se': 78.971, 'Br': 79.904, 'Kr': 83.798, 'Rb': 85.468, 'Sr': 87.62,
    'Y': 88.906, 'Zr': 91.224, 'Nb': 92.906, 'Mo': 95.95, 'Tc': 98.0, 'Ru': 101.07,
    'Rh': 102.906, 'Pd': 106.42, 'Ag': 107.868, 'Cd': 112.414, 'In': 114.818, 'Sn': 118.710,
    'Sb': 121.760, 'Te': 127.60, 'I': 126.904, 'Xe': 131.293, 'Cs': 132.905, 'Ba': 137.327,
    'La': 138.905, 'Ce': 140.116, 'Pr': 140.908, 'Nd': 144.242, 'Sm': 150.36, 'Eu': 151.964,
    'Gd': 157.25, 'Tb': 158.925, 'Dy': 162.500, 'Ho': 164.930, 'Er': 167.259, 'Tm': 168.934,
    'Yb': 173.045, 'Lu': 174.967, 'Hf': 178.486, 'Ta': 180.948, 'W': 183.84, 'Re': 186.207,
    'Os': 190.23, 'Ir': 192.217, 'Pt': 195.084, 'Au': 196.967, 'Hg': 200.592, 'Tl': 204.38,
    'Pb': 207.2, 'Bi': 208.980, 'Ra': 226.025, 'Th': 232.038, 'Pa': 231.036, 'U': 238.029,
    'Np': 237.048, 'Pu': 244.064,
}

# Passed as `mass_shift` to have it derived from the element and the label.
AUTOMATIC = 'auto'


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
        self.mass_shift = None
        self.reactions = []
        self.reactions_needing_name = []
        self.unknown_element = None
        self.labelled = {}
        self.uncounted = []
        self.consuming = []

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

        if self.unknown_element:
            lines.append(
                f"  '{self.unknown_element}' is not in ATOMIC_WEIGHTS, so no mass shift could be "
                f'derived and every copy keeps its parent weight. Set mass_shift to correct that.'
            )
        elif self.mass_shift:
            lines.append(
                f'  molecular weights shifted by {self.mass_shift:+g} per atom of {self.element}'
            )
        else:
            lines.append('  molecular weights copied from the parents, unshifted')

        for section, names in self.added.items():
            lines.append(f'  {section}: {len(names)} added, e.g. {names[:4]}')

        if self.kinetics:
            lines.append(f'  mineral kinetics copied for: {self.kinetics}')

        if self.uncounted:
            lines.append(
                f'  atoms not counted, so these keep their parent weight: {self.uncounted}'
            )

        if self.consuming:
            lines.append(
                f'  these consume {self.element} rather than containing it -- a negative atom count '
                f'-- so they keep their parent weight rather than being made lighter: '
                f'{self.consuming}'
            )

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

        if self.reactions:
            lines.append(f'  namelist reactions added: {self.reactions}')

        if self.reactions_needing_name:
            lines.append(
                f'  namelist reactions NOT added, no name can be derived -- give one in '
                f'`reaction_names`: {self.reactions_needing_name}'
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


def count_atoms(database, labelled, parents, report=None, passes=100):
    """Return how many atoms of the element each labelled species holds.

    A species holds as many atoms as its reaction's signed coefficients on labelled species say it
    does: `Cr2O7--`, written as two `CrO4--`, holds two. A primary species holds one, by construction.

    Counted after the labelled set is complete, and relaxed until nothing changes, rather than as the
    set is built. Counting during the walk fixed each species' total from whatever was labelled at
    the moment it was reached, so a species standing on both the parent and a species labelled later
    came out short -- and was never revised, because a count was only ever written once. File order
    decided whether a weight was right.

    A count can come out **negative**, which means the entry is not an isotopologue by composition.
    The ex9 Rifle database has `Fe(OH)3_HS = -0.5 HS- - 2.5 H+ + 1 Fe++ + 3 H2O`, a pseudo-phase for
    ferrihydrite reduced by sulfide: the sulfur is consumed to form it, not held in it. Taken at face
    value that is -0.5 atoms of S, and the mass shift would *lower* the copy's weight -- by 1 for
    S34, silently. Those are reported and left at their parent's weight instead.
    """
    lookup = entries_by_name(database)
    atoms = {name: 1.0 for name in parents}

    for _ in range(passes):
        changed = False

        for name in labelled:
            if name in parents:
                continue

            found = lookup.get(name)
            reaction = getattr(found[1], 'reaction', None) if found else None

            if reaction is None:
                continue

            total = 0.0
            complete = True

            for species, coefficient in reaction.products.items():
                if species in labelled:
                    if species in atoms:
                        total += coefficient * atoms[species]
                    else:
                        complete = False

            for species, coefficient in reaction.reactants.items():
                if species != name and species in labelled:
                    if species in atoms:
                        total -= coefficient * atoms[species]
                    else:
                        complete = False

            if complete and atoms.get(name) != total:
                atoms[name] = total
                changed = True

        if not changed:
            break
    else:
        # Only reachable if the reactions form a cycle, which a CrunchTope database should not.
        if report is not None:
            report.uncounted = sorted(set(labelled) - set(atoms))

    if report is not None and not report.uncounted:
        report.uncounted = sorted(set(labelled) - set(atoms))

    consuming = sorted(name for name, count in atoms.items() if count < 0)

    if consuming:
        if report is not None:
            report.consuming = consuming
        for name in consuming:
            atoms[name] = 0.0

    return atoms


def close_over_reactions(database, element, label, labelled, wanted, names, report):
    """Extend the labelled set until nothing new references it.

    Labelling cannot stop at the primary species. A CrunchTope reaction may be written in terms of
    primary, secondary or gas species -- `Cr(OH)3` in SukindaCr53.dbs is written on `Cr+++`, which is
    secondary -- so the mineral is only reached once `Cr+++` itself has been labelled. Repeating
    until the set stops growing is what gets from `CrO4--` to `Cr53(OH)3`.
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

                references = any(
                    species in labelled
                    for species in set(reaction.products) | (set(reaction.reactants) - {name})
                )

                if not references:
                    continue

                new_name = names.get(name) or isotope_name(name, element, label)

                if new_name is None:
                    report.needs_name[name] = section
                    continue

                labelled[name] = new_name
                growing = True

    return labelled


def copy_weight(entry, new_name, weights, mass_shift, atoms):
    """Return the molecular weight text for a copy, or None to keep the parent's."""
    if 'weight' not in entry.parameters:
        return None

    if new_name in weights:
        return f'{weights[new_name]:g}'

    if mass_shift:
        return f'{entry.weight + mass_shift * atoms:.4f}'

    return None


def derived_mass_shift(element, label, report=None):
    """Return how much heavier the isotope is than the element, per atom.

    The label is a mass number, so the shift is the label minus the element's rounded standard atomic
    weight: 53 - 52 for Cr53, which is the +1 the hand-built Cr53 system uses throughout. For Ca44
    this gives +4, so `Ca44++` comes out at 44.078 where the hand-built database has a flat 44.0000 --
    both are defensible, and `weights` overrides it.

    Returns:
        The shift, or None for an element not in ATOMIC_WEIGHTS, in which case the parent's weight is
        kept and the report says so.
    """
    if element not in ATOMIC_WEIGHTS:
        if report is not None:
            report.unknown_element = element

        return None

    return int(label) - round(ATOMIC_WEIGHTS[element])


def add_isotope(database, element, label, parents=None, species=None, names=None, weights=None,
                mass_shift=AUTOMATIC, kinetics_from=None):
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
            atom count taken from its stoichiometry. Defaults to 'auto', which derives it as the
            label minus the element's rounded standard atomic weight -- +1 for Cr53, +2 for S34, +4
            for Ca44 -- so an isotopologue weighs what it should without being told. Give a number to
            set it, or None to keep the parent's weight unshifted. Note that the shipped databases do
            not agree with each other here: the hand-built Cr53 system uses +1 throughout, S34 left
            the weights alone, and Ca44 was given a flat 44.0000. `weights` overrides per species.

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

    if mass_shift == AUTOMATIC:
        mass_shift = derived_mass_shift(element, label, report)

    report.mass_shift = mass_shift

    parents_labelled = list(labelled)

    labelled = close_over_reactions(
        database, element, label, labelled, wanted, names, report
    )
    atoms = count_atoms(database, labelled, parents_labelled, report)
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
                               dict(kinetics_from or {}), labelled)
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
    # Only what the database now actually holds. `labelled` is the whole closure -- every species the
    # isotope could apply to -- and a scope means most of it was never written. Handing that to
    # add_isotope_reactions pointed namelist reactions at species CrunchTope would not find. Read
    # back after the reparse rather than taken from what this call added, since a species already
    # there from an earlier run counts as available too.
    report.labelled = {
        name: new_name for name, new_name in labelled.items() if in_database(database, new_name)
    }

    return report


def suspected_isotope_pairs(database):
    """Names that look like labelled forms of another species the database also holds.

    Only for warning, never for editing. The test is that deleting a run of digits immediately after
    an element symbol turns one name in the database into another -- which `H2O2` and `H2O` satisfy
    without being an isotope pair at all, so acting on this would corrupt a database. It is good
    enough to say "this database appears to contain isotopologues" and let the user declare them.

    Args:
        database: The Database to inspect.

    Returns:
        {suspected isotopologue: suspected parent}.
    """
    names = set()
    for section in ISOTOPE_SECTIONS:
        names.update(getattr(database, section, {}))

    symbols = '|'.join(sorted(ATOMIC_WEIGHTS, key=len, reverse=True))
    label = re.compile(f'({symbols})([0-9]+)')

    found = {}

    for name in names:
        for match in label.finditer(name):
            stripped = name[:match.end(1)] + name[match.end(2):]
            if stripped != name and stripped in names:
                found[name] = stripped
                break

    return found


def in_database(database, name):
    """Whether a species of this name is in any of the sections an isotope touches."""
    return any(name in getattr(database, section, {}) for section in ISOTOPE_SECTIONS)


def requote(database, line_index, token_index, new):
    """Return `new` quoted exactly as the token it replaces was.

    Species names are quoted in the row sections and bare in the mineral kinetics block, and a name
    that loses its quotes changes where the row's fields fall.
    """
    line = database.lines[line_index]
    _, start, end = tokenise(line)[token_index]

    return f"'{new}'" if line[start:end].startswith("'") else new


def kinetics_copies(database, minerals, names, element, label, kinetics_from, labelled):
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
            )] + [relabel_quoted(line, labelled) for line in block[1:]]
            copies.append((key.replace(source, new_name, 1), renamed))

    return copies


def relabel_quoted(line, labelled):
    """Relabel any quoted species name in a line, leaving everything else alone.

    A mineral kinetics block can point at another species -- a BiomassDecay stanza names the biomass
    it consumes as `biomass = 'C5H7O2NSO4(s)'` -- and a labelled mineral's copy should point at the
    labelled biomass. Only quoted tokens are considered, because the unquoted text in these blocks
    includes `rate(25C)` and `(kcal/mole)`, which a carbon isotope would otherwise mangle.
    """
    def relabel(match):
        species = match.group(1)

        return f"'{labelled[species]}'" if species in labelled else match.group(0)

    return re.sub(r"'([^']*)'", relabel, line)


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


# Species appear in these namelists both bare and prefixed, as 'CrO4--' in a stoichiometry and
# 'tot_CrO4--' in a rate dependence, so a prefix is stripped before matching and put back after.
SPECIES_PREFIXES = ('tot_',)

# The namelist groups a labelled reaction may live in. f90nml lowercases group names on read.
REACTION_GROUPS = ('aqueous', 'aqueouskinetics', 'catabolicpathway')


def split_prefix(text):
    """Return (prefix, species) for a possibly prefixed species name."""
    for prefix in SPECIES_PREFIXES:
        if text.startswith(prefix):
            return prefix, text[len(prefix):]

    return '', text


def relabel_value(value, labelled):
    """Return a namelist value with any labelled species in it relabelled.

    Only exact species names are substituted, prefix aside. Matching by pattern instead would reach
    things that merely look like formulae -- a `type = 'MonodBiomass'`, a filename -- and a namelist
    holds plenty of those.
    """
    if isinstance(value, str):
        prefix, species = split_prefix(value)

        return f'{prefix}{labelled[species]}' if species in labelled else value

    if isinstance(value, list):
        return [relabel_value(item, labelled) for item in value]

    return value


def references_labelled(entry, labelled):
    """Whether a namelist entry names any of the labelled species."""
    for key, value in entry.items():
        if key == 'name':
            continue

        values = value if isinstance(value, list) else [value]

        for item in values:
            if isinstance(item, str) and split_prefix(item)[1] in labelled:
                return True

    return False


def group_entries(namelist, group):
    """Return a namelist group's entries as a list.

    f90nml gives a list only where a group appears more than once; a single occurrence comes back as
    the entry itself, and iterating that yields its keys rather than the entry. ex9's aqueous
    database has one &AqueousKinetics block until an isotope adds a second.
    """
    try:
        entries = namelist.namelist[group]
    except KeyError:
        return []

    return list(entries) if isinstance(entries, list) else [entries]


def add_isotope_reactions(namelist, element, label, labelled, names=None, keq_offset=None):
    """Duplicate a namelist's reactions for an isotope, in place.

    The thermodynamic database is only half an isotope system. A model also needs its aqueous
    kinetics reactions duplicated -- SukindaCr53.dbs's model has `Cr53_Fe_redox`, `Cr53_H2S_redox`
    and `Cr53_S(s)_redox` alongside their unlabelled counterparts -- and, for microbial models, its
    catabolic pathways.

    Each reaction referencing a labelled species is copied with the species relabelled and the
    reaction's own name labelled by the same formula rule, which happens to suit these names:
    `Cr_Fe_redox` becomes `Cr53_Fe_redox` because the underscore is neither lowercase nor a digit.
    Names it cannot derive -- `Sulfate_reduction`, where 'S' is the start of a word -- are reported.

    Rates are copied unchanged. **Kinetic fractionation belongs in the input file**, where CrunchTope's
    AQUEOUS_KINETICS block sets the rate per reaction and Omphalos already sweeps it: the Sukinda deck
    carries `Cr_Fe_redox -rate 29.59E6` against `Cr53_Fe_redox -rate 29.51E6`, a ratio of 0.9973.
    `keq_offset` is here for the other kind -- equilibrium fractionation, which does belong in the
    database, as an offset on the labelled reaction's equilibrium constant.

    Args:
        namelist: A CrunchNameList to add to, or None.
        element: The element symbol.
        label: The mass number.
        labelled: {existing species: labelled species}, as add_isotope worked out.
        names: {existing reaction name: labelled name}, for names the rule cannot derive.
        keq_offset: Added to the copy's `keq` where it has one. For equilibrium fractionation.

    Returns:
        A (added, needs_name) pair of lists.
    """
    import copy as copy_module

    added, needs_name = [], []

    if namelist is None or not getattr(namelist, 'namelist', None):
        return added, needs_name

    names = dict(names or {})

    for group in REACTION_GROUPS:
        entries = group_entries(namelist, group)
        existing = {entry['name'] for entry in entries if 'name' in entry}

        for entry in entries:
            name = entry.get('name')

            if name is None or not references_labelled(entry, labelled):
                continue

            new_name = names.get(name) or isotope_name(name, element, label)

            if new_name is None:
                if name not in needs_name:
                    needs_name.append(name)
                continue

            if new_name in existing:
                continue

            copied = copy_module.deepcopy(dict(entry))
            copied['name'] = new_name

            for key, value in copied.items():
                if key != 'name':
                    copied[key] = relabel_value(value, labelled)

            if keq_offset is not None and 'keq' in copied:
                copied['keq'] = copied['keq'] + keq_offset

            namelist.namelist.add_cogroup(group, copied)
            existing.add(new_name)
            added.append(f'{group}/{new_name}')

    return added, needs_name
