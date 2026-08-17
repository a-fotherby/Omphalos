"""Unit tests for omphalos/isotopes.py.

The ground truth is `SukindaCr53.dbs`, which carries three isotope systems built by hand -- Ca44,
S34 and Cr53. Rebuilding those and comparing is what these tests do, because a name or a
stoichiometry that is subtly wrong produces a database CrunchTope reads happily.
"""

from pathlib import Path

import pytest

from omphalos.database import Database
from omphalos.isotopes import add_isotope, isotope_name, labelled_primaries

DB_PATH = Path(__file__).parent.parent / 'omphalos_test' / 'SukindaCr53.dbs'


@pytest.fixture(scope='module')
def db():
    return Database(str(DB_PATH))


@pytest.fixture
def stripped(tmp_path):
    """A copy of the database with one isotope system removed, for the tool to put back."""
    def strip(isotope):
        lines = DB_PATH.read_text(newline='').splitlines(keepends=True)
        path = tmp_path / f'no_{isotope}.dbs'
        path.write_text(''.join(line for line in lines if isotope not in line), newline='')
        return Database(str(path))

    return strip


class TestIsotopeName:
    """An element symbol is a capital and optional lowercase, which is what makes this safe."""

    @pytest.mark.parametrize('name,element,label,expected', [
        ('Ca++', 'Ca', '44', 'Ca44++'),
        ('CaCO3(aq)', 'Ca', '44', 'Ca44CO3(aq)'),
        ('Ca(CH3COO)2(aq)', 'Ca', '44', 'Ca44(CH3COO)2(aq)'),
        ('SO4--', 'S', '34', 'S34O4--'),
        ('HS-', 'S', '34', 'HS34-'),
        ('H2S(aq)', 'S', '34', 'H2S34(aq)'),
        ('FeS(am)', 'S', '34', 'FeS34(am)'),
        ('CrO4--', 'Cr', '53', 'Cr53O4--'),
        ('Cr(OH)3', 'Cr', '53', 'Cr53(OH)3'),
        # Two isotopes in one species: the substitutions compose.
        ('CaS34O4(aq)', 'Ca', '44', 'Ca44S34O4(aq)'),
    ])
    def test_formula_names_are_labelled(self, name, element, label, expected):
        assert isotope_name(name, element, label) == expected

    @pytest.mark.parametrize('name,element', [
        ('Calcite', 'Ca'),      # would give the nonsense 'Ca44lcite'
        ('CalciteRifle', 'Ca'),
        ('Dolomite', 'Ca'),     # contains calcium, but not as a symbol in its name
        ('Cl-', 'C'),           # chlorine, not carbon
        ('SiO2(aq)', 'S'),      # silicon, not sulfur
        ('Cs+', 'C'),           # caesium, not carbon
    ])
    def test_a_symbol_followed_by_lowercase_is_a_different_element(self, name, element):
        assert isotope_name(name, element, '13') is None

    @pytest.mark.parametrize('name,element', [
        ('Ca2Al2O5.8H2O', 'Ca'),   # 'Ca442Al2O5.8H2O' cannot be read back apart
        ('Cr2O7--', 'Cr'),
        ('C3H4O4', 'C'),
    ])
    def test_a_subscripted_symbol_is_declined(self, name, element):
        assert isotope_name(name, element, '44') is None

    def test_the_rule_reproduces_every_name_already_in_the_database(self, db):
        # 40 isotopologues, built by hand. If the rule disagrees with any of them it is wrong.
        sections = ['primary_species', 'secondary_species', 'gases', 'minerals',
                    'surface_complexation', 'exchange']
        checked = 0

        for element, label in [('Ca', '44'), ('S', '34'), ('Cr', '53')]:
            isotope = f'{element}{label}'
            for section in sections:
                for name in getattr(db, section):
                    if isotope not in name:
                        continue
                    parent = name.replace(isotope, element)
                    generated = isotope_name(parent, element, label)
                    # Subscripted names had to be entered by hand and the rule declines them.
                    if generated is not None:
                        assert generated == name, f'{parent} -> {generated}, database has {name}'
                        checked += 1

        assert checked > 30, f'only {checked} names were checked'


class TestLabelledPrimaries:
    def test_every_primary_carrying_the_element_is_labelled(self, db):
        # Sulfur is present in several redox states, and a species written on the one that was
        # missed would have no isotopologue.
        inferred = labelled_primaries(db, 'S', '34')

        assert {'SO4--': 'S34O4--', 'HS-': 'HS34-', 'S(aq)': 'S34(aq)'}.items() <= inferred.items()

    def test_inference_reads_names_and_can_over_reach(self, db):
        # 'CIS-12DCE' is cis-1,2-dichloroethene: 'CIS' is a word in capitals, not carbon-iodine-
        # sulfur. No rule distinguishes that from a formula, which is why the report says when the
        # parents were inferred and `parents` exists to be explicit.
        assert 'CIS-12DCE' in labelled_primaries(db, 'S', '34')

    def test_an_explicit_list_is_not_flagged_as_inferred(self, stripped):
        database = stripped('S34')
        report = add_isotope(database, 'S', '34', parents=['SO4--'], species=[])

        assert not report.inferred_parents
        assert 'inferred' not in report.summary()

    def test_an_inferred_list_is_flagged_for_checking(self, stripped):
        database = stripped('S34')
        report = add_isotope(database, 'S', '34', species=[])

        assert report.inferred_parents
        assert 'CHECK THESE' in report.summary()

    def test_an_explicit_parent_list_is_honoured(self, db):
        assert labelled_primaries(db, 'S', '34', ['SO4--']) == {'SO4--': 'S34O4--'}

    def test_a_parent_that_is_not_primary_is_refused(self, db):
        # Cr+++ is a secondary species here, so it cannot be a parent.
        with pytest.raises(KeyError, match='not primary species'):
            labelled_primaries(db, 'Cr', '53', ['Cr+++'])

    def test_an_element_with_no_primary_species_is_refused(self, db):
        # Xenon is in this database as Xe(aq), so pick a symbol that genuinely is not.
        with pytest.raises(ValueError, match='nothing to label'):
            labelled_primaries(db, 'Bk', '247')


class TestRebuildingAHandBuiltSystem:
    """The strongest check available: strip a system out and put it back."""

    @pytest.fixture
    def rebuilt_cr53(self, stripped, db):
        # No mass_shift given: the default derives +1, which is what this system uses.
        database = stripped('Cr53')
        report = add_isotope(database, 'Cr', '53')
        return database, report

    def test_the_primary_species_is_labelled(self, rebuilt_cr53):
        database, report = rebuilt_cr53

        assert report.parents == ['CrO4--']
        assert 'Cr53O4--' in database.primary_species

    def test_labelling_reaches_past_the_primaries(self, rebuilt_cr53):
        # Cr(OH)3 is written on Cr+++, a secondary species, so it is only reached once Cr+++ has
        # itself been labelled. Stopping at the primaries would miss the mineral entirely.
        database, _ = rebuilt_cr53

        assert 'Cr53+++' in database.secondary_species
        assert 'Cr53(OH)3' in database.minerals

    def test_the_reaction_references_the_labelled_species(self, rebuilt_cr53):
        database, _ = rebuilt_cr53
        reaction = database.minerals['Cr53(OH)3'].reaction

        assert 'Cr53+++' in reaction.products
        assert 'Cr+++' not in reaction.products

    def test_the_rows_match_the_hand_built_ones(self, rebuilt_cr53, db):
        database, _ = rebuilt_cr53
        compared = 0

        for section in ['primary_species', 'secondary_species', 'minerals']:
            for name, hand in getattr(db, section).items():
                if 'Cr53' not in name or name not in getattr(database, section):
                    continue
                tool = getattr(database, section)[name]
                # The weights differ on three rows where the hand-built values do not follow that
                # system's own +1-per-atom convention, so compare everything except the weight.
                assert (db.lines[hand.line_index].split()[:-1]
                        == database.lines[tool.line_index].split()[:-1]), name
                compared += 1

        assert compared > 10

    def test_the_kinetics_entry_is_copied(self, rebuilt_cr53, db):
        # A mineral with no kinetics entry has no rate and CrunchTope stops.
        database, report = rebuilt_cr53

        assert report.kinetics == ['Cr53(OH)3&default']
        assert (database.mineral_kinetics['Cr53(OH)3&default'].attributes
                == db.mineral_kinetics['Cr53(OH)3&default'].attributes)

    def test_the_kinetics_section_still_ends_with_a_separator(self, rebuilt_cr53):
        # CrunchTope reads this section by scanning forward for a line starting '+' (BreakFind).
        # Without a separator after the last entry it reads to end of file and dies.
        database, _ = rebuilt_cr53
        _, end = database.sections['mineral kinetics']

        assert database.lines[end - 1].strip().startswith('+--')

    def test_the_result_round_trips(self, rebuilt_cr53, tmp_path):
        database, _ = rebuilt_cr53
        out = tmp_path / 'rebuilt.dbs'
        database.print(str(out))

        assert 'Cr53(OH)3' in Database(str(out)).minerals

    def test_the_added_rows_are_editable(self, rebuilt_cr53):
        database, _ = rebuilt_cr53
        database.modify('minerals', 'Cr53(OH)3', 'log_k', 1.0)

        assert database.value('minerals', 'Cr53(OH)3', 'log_k') == pytest.approx(
            [1.0] * database.temp_points)


class TestAtomCountsAndWeights:
    def test_atoms_come_from_the_stoichiometry(self, stripped):
        # Cr2O7-- is written as two CrO4--, so it holds two chromium atoms. Its name has to be
        # given, since the rule declines subscripted formulae.
        database = stripped('Cr53')
        report = add_isotope(database, 'Cr', '53', names={
            'Cr2O7--': 'Cr53_2O7--', 'Cr3(OH)4(5+)': 'Cr53_3(OH)4(5+)'})

        assert report.atoms['CrO4--'] == pytest.approx(1.0)
        assert report.atoms['Cr2O7--'] == pytest.approx(2.0)
        assert report.atoms['Cr3(OH)4(5+)'] == pytest.approx(3.0)

    def test_the_shift_is_derived_by_default(self, stripped, db):
        # 53 minus Cr's rounded standard atomic weight of 52, which is the +1 the hand-built Cr53
        # system uses throughout.
        database = stripped('Cr53')
        report = add_isotope(database, 'Cr', '53')

        assert report.mass_shift == 1
        assert database.secondary_species['Cr53+++'].weight == pytest.approx(
            db.secondary_species['Cr+++'].weight + 1)

    @pytest.mark.parametrize('element,label,expected', [
        ('Cr', '53', 1), ('Ca', '44', 4), ('S', '34', 2), ('C', '13', 1),
        ('Fe', '56', 0),   # 56-Fe is the common one, so no shift
    ])
    def test_derived_shifts(self, element, label, expected):
        from omphalos.isotopes import derived_mass_shift

        assert derived_mass_shift(element, label) == expected

    def test_an_unknown_element_keeps_the_parents_weight_and_says_so(self, stripped, db):
        from omphalos.isotopes import derived_mass_shift

        assert derived_mass_shift('Zz', '99') is None

    def test_mass_shift_none_keeps_the_parents_weight(self, stripped, db):
        database = stripped('Cr53')
        add_isotope(database, 'Cr', '53', mass_shift=None)

        assert database.secondary_species['Cr53+++'].weight == pytest.approx(
            db.secondary_species['Cr+++'].weight)

    def test_a_mass_shift_is_applied_per_atom(self, stripped, db):
        database = stripped('Cr53')
        add_isotope(database, 'Cr', '53', names={'Cr2O7--': 'Cr53_2O7--'}, mass_shift=1)

        assert database.secondary_species['Cr53+++'].weight == pytest.approx(
            db.secondary_species['Cr+++'].weight + 1)
        assert database.secondary_species['Cr53_2O7--'].weight == pytest.approx(
            db.secondary_species['Cr2O7--'].weight + 2)

    def test_the_summary_states_the_shift(self, stripped):
        database = stripped('Cr53')
        report = add_isotope(database, 'Cr', '53', species=[])

        assert 'shifted by +1 per atom of Cr' in report.summary()

    def test_an_explicit_weight_wins(self, stripped):
        database = stripped('Ca44')
        add_isotope(database, 'Ca', '44', species=[], weights={'Ca44++': 44.0})

        assert database.primary_species['Ca44++'].weight == pytest.approx(44.0)


class TestScope:
    def test_by_default_everything_containing_the_element_is_labelled(self, stripped):
        database = stripped('Ca44')
        report = add_isotope(database, 'Ca', '44')

        # A full compilation holds every calcium-bearing phase anyone has measured.
        assert report.counts['added'] > 50

    def test_a_species_list_restricts_the_copies(self, stripped):
        database = stripped('Ca44')
        report = add_isotope(database, 'Ca', '44', species=['CaCO3(aq)', 'CaCl+'])

        assert sorted(report.added['secondary_species']) == ['Ca44CO3(aq)', 'Ca44Cl+']

    def test_the_parents_are_labelled_whatever_the_scope_says(self, stripped):
        # Nothing else can be written without them.
        database = stripped('Ca44')
        add_isotope(database, 'Ca', '44', species=[])

        assert 'Ca44++' in database.primary_species


class TestReporting:
    def test_species_that_cannot_be_named_are_listed_not_guessed(self, stripped):
        database = stripped('Ca44')
        report = add_isotope(database, 'Ca', '44', species=['Calcite', 'Dolomite', 'Gypsum'])

        assert set(report.needs_name) == {'Calcite', 'Dolomite', 'Gypsum'}
        assert not report.added.get('minerals')

    def test_a_given_name_is_used_for_those(self, stripped):
        database = stripped('Ca44')
        report = add_isotope(database, 'Ca', '44', species=['Calcite'],
                             names={'Calcite': 'Calcite44'})

        assert 'Calcite44' in database.minerals
        assert not report.needs_name

    def test_a_species_already_present_is_left_alone(self, db, tmp_path):
        # Adding Ca44 to a database that already has it must not double the rows.
        database = Database(str(DB_PATH))
        report = add_isotope(database, 'Ca', '44', species=['CaCO3(aq)'])

        assert 'Ca44CO3(aq)' in report.already_present
        assert not report.added.get('secondary_species')

    def test_the_summary_names_what_it_could_not_do(self, stripped):
        database = stripped('Ca44')
        report = add_isotope(database, 'Ca', '44', species=['Calcite'])

        assert 'Calcite' in report.summary()
        assert 'give one in `names`' in report.summary()


class TestConfigSurface:
    """`database_isotopes:` is a list of systems, applied before anything else edits the database."""

    @pytest.fixture
    def in_test_dir(self, omphalos_test_dir):
        import os
        original = os.getcwd()
        os.chdir(omphalos_test_dir)
        try:
            yield omphalos_test_dir
        finally:
            os.chdir(original)

    @pytest.fixture
    def config(self, sample_config):
        import copy as copy_module
        config = copy_module.deepcopy(sample_config)
        config['number_of_files'] = 2
        return config

    def _template(self, config):
        import contextlib
        import io

        from omphalos.template import Template

        with contextlib.redirect_stdout(io.StringIO()):
            return Template(config)

    def test_a_system_is_added(self, config, in_test_dir):
        # The database already has Cr53, so ask for one it does not: Ca43.
        config['database_isotopes'] = [
            {'element': 'Ca', 'label': 43, 'species': ['CaCO3(aq)'], 'mass_shift': 3}
        ]
        template = self._template(config)

        assert 'Ca43++' in template.database.primary_species
        assert 'Ca43CO3(aq)' in template.database.secondary_species

    def test_the_label_may_be_a_number_in_the_yaml(self, config, in_test_dir):
        config['database_isotopes'] = [{'element': 'Ca', 'label': 43, 'species': []}]

        assert 'Ca43++' in self._template(config).database.primary_species

    def test_several_systems_are_applied_in_order(self, config, in_test_dir):
        config['database_isotopes'] = [
            {'element': 'Ca', 'label': 43, 'species': ['CaCO3(aq)']},
            {'element': 'Ca', 'label': 46, 'species': ['CaCO3(aq)']},
        ]
        template = self._template(config)

        assert 'Ca43CO3(aq)' in template.database.secondary_species
        assert 'Ca46CO3(aq)' in template.database.secondary_species

    def test_no_isotopes_asked_for_means_none_added(self, config, in_test_dir):
        config['database_parameters'] = {'exchange': {'CaXRifle': {'log_k': ['constant', -1.0]}}}
        template = self._template(config)

        assert template.add_isotopes() == []

    def test_asking_only_for_isotopes_still_parses_the_database(self, config, in_test_dir):
        config.pop('database_parameters', None)
        config['database_isotopes'] = [{'element': 'Ca', 'label': 43, 'species': []}]

        assert self._template(config).database is not None

    def test_the_isotopes_reach_every_run(self, config, in_test_dir, tmp_path):
        import contextlib
        import io

        from omphalos import generate_inputs as gi

        config['database_isotopes'] = [
            {'element': 'Ca', 'label': 43, 'species': ['CaCO3(aq)']}
        ]
        template = self._template(config)

        with contextlib.redirect_stdout(io.StringIO()):
            file_dict = gi.configure_input_files(template, str(tmp_path) + '/', rhea=True)

        for run in file_dict:
            assert 'Ca43CO3(aq)' in file_dict[run].database.secondary_species

    def test_a_sweep_can_name_an_added_species(self, config, in_test_dir, tmp_path):
        # The isotopes go in first precisely so that everything downstream can see them.
        import contextlib
        import io

        from omphalos import generate_inputs as gi

        config['database_isotopes'] = [
            {'element': 'Ca', 'label': 43, 'species': ['CaCO3(aq)']}
        ]
        config['database_parameters'] = {
            'secondary_species': {'Ca43CO3(aq)': {'log_k': ['custom', [1.0, 2.0]]}}
        }
        template = self._template(config)

        with contextlib.redirect_stdout(io.StringIO()):
            file_dict = gi.configure_input_files(template, str(tmp_path) + '/', rhea=True)

        found = [file_dict[run].database.value('secondary_species', 'Ca43CO3(aq)', 'log_k')[0]
                 for run in file_dict]
        assert found == pytest.approx([1.0, 2.0])


class TestKineticsWithoutAParentEntry:
    """A mineral CrunchTope has no rate law for stops the run, and says so unhelpfully.

    The ex9 sulfur model has hand-built `S32` and `S34` minerals with their own rates and none on
    the plain `S` they came from, so a copy of `S` has nowhere to get a rate law from.
    """

    @pytest.fixture
    def without_kinetics(self, stripped):
        """Add an isotope of a mineral whose parent has no kinetics entry."""
        database = stripped('Cr53')
        # Chromite has no kinetics entry in this database.
        report = add_isotope(database, 'Cr', '53', species=['Chromite'],
                             names={'Chromite': 'Chromite53'})
        return database, report

    def test_the_mineral_is_still_added(self, without_kinetics):
        database, _ = without_kinetics

        assert 'Chromite53' in database.minerals

    def test_but_the_missing_rate_law_is_reported(self, without_kinetics):
        _, report = without_kinetics

        assert 'Chromite53' in report.no_kinetics

    def test_and_the_summary_says_what_will_happen(self, without_kinetics):
        _, report = without_kinetics

        assert 'Kinetic mineral reaction not found in database' in report.summary()

    def test_a_mineral_whose_parent_has_kinetics_is_not_flagged(self, stripped):
        database = stripped('Cr53')
        report = add_isotope(database, 'Cr', '53', species=['Cr(OH)3'])

        assert report.kinetics == ['Cr53(OH)3&default']
        assert not report.no_kinetics

    def test_kinetics_can_be_taken_from_another_mineral(self, stripped, db):
        # {'S34': 'S32'} is what the ex9 model needs.
        database = stripped('Cr53')
        report = add_isotope(database, 'Cr', '53', species=['Chromite'],
                             names={'Chromite': 'Chromite53'},
                             kinetics_from={'Chromite53': 'Cr(OH)3'})

        assert 'Chromite53&default' in database.mineral_kinetics
        assert not report.no_kinetics
        # Copied verbatim apart from the name, which is what the hand-built systems do -- the ex9
        # S34 block keeps its parent's `dependence : H2S(aq)` unchanged.
        assert (database.mineral_kinetics['Chromite53&default'].attributes
                == db.mineral_kinetics['Cr(OH)3&default'].attributes)


class TestScopePullsInDependencies:
    """A species cannot be written unless what its reaction stands on is written too."""

    def test_asking_for_a_mineral_brings_its_basis_with_it(self, stripped):
        # Chromite is written on Cr+++, which is written on CrO4--. Asking for Chromite alone has to
        # produce all three, or its row references a Cr53+++ that does not exist.
        database = stripped('Cr53')
        add_isotope(database, 'Cr', '53', species=['Chromite'],
                    names={'Chromite': 'Chromite53'})

        assert 'Chromite53' in database.minerals
        assert 'Cr53+++' in database.secondary_species
        assert 'Cr53O4--' in database.primary_species

    def test_nothing_the_scope_does_not_need_is_added(self, stripped):
        database = stripped('Cr53')
        report = add_isotope(database, 'Cr', '53', species=['Cr(OH)3'])

        # Cr(OH)3 stands on Cr+++, which stands on CrO4--. Nothing else.
        assert sorted(report.added['secondary_species']) == ['Cr53+++']
        assert sorted(report.added['minerals']) == ['Cr53(OH)3']

    def test_every_reference_in_an_added_row_resolves(self, stripped):
        # The property that matters: no row may name a species the database does not hold.
        database = stripped('Cr53')
        add_isotope(database, 'Cr', '53', species=['Chromite'],
                    names={'Chromite': 'Chromite53'})

        known = set()
        for section in ['primary_species', 'secondary_species', 'gases', 'minerals']:
            known |= set(getattr(database, section))

        for section in ['secondary_species', 'minerals']:
            for name, entry in getattr(database, section).items():
                if 'Cr53' not in name:
                    continue
                for species in entry.reaction.products:
                    assert species in known, f'{name} references unknown {species}'


class TestNamelistReactions:
    """A thermodynamic isotopologue with no reactions does nothing.

    The aqueous kinetics namelist and the catabolic pathways need duplicating too. Ground truth is
    tests/omphalos_test/aqueous.dbs, which carries three hand-built Cr53 reactions in each of
    &Aqueous and &AqueousKinetics.
    """

    AQUEOUS = Path(__file__).parent.parent / 'omphalos_test' / 'aqueous.dbs'
    LABELLED = {'CrO4--': 'Cr53O4--', 'Cr+++': 'Cr53+++'}

    @pytest.fixture
    def stripped_namelist(self, tmp_path):
        """The namelist with every Cr53 reaction block removed."""
        import re

        from omphalos.namelist import CrunchNameList

        text = self.AQUEOUS.read_text()
        blocks = re.split(r'(?=^&)', text, flags=re.M)
        path = tmp_path / 'no_cr53.dbs'
        path.write_text(''.join(b for b in blocks if 'Cr53' not in b))
        return CrunchNameList(str(path))

    @pytest.fixture
    def original_namelist(self):
        from omphalos.namelist import CrunchNameList

        return CrunchNameList(str(self.AQUEOUS))

    def test_the_reactions_are_rebuilt_identically(self, stripped_namelist, original_namelist):
        from omphalos.isotopes import add_isotope_reactions

        added, needs_name = add_isotope_reactions(
            stripped_namelist, 'Cr', '53', self.LABELLED)

        assert not needs_name
        assert len(added) == 6

        for group in ('aqueous', 'aqueouskinetics'):
            for hand in original_namelist.namelist[group]:
                if 'Cr53' not in hand['name']:
                    continue
                tool = next(e for e in stripped_namelist.namelist[group]
                            if e['name'] == hand['name'])
                assert dict(tool) == dict(hand), hand['name']

    def test_the_reaction_name_takes_the_formula_rule(self):
        # 'Cr_Fe_redox' works because the underscore is neither lowercase nor a digit.
        assert isotope_name('Cr_Fe_redox', 'Cr', '53') == 'Cr53_Fe_redox'

    def test_a_reaction_named_as_a_word_is_reported(self, stripped_namelist):
        # 'Sulfate_reduction' starts with a word, not a symbol, so the rule declines it.
        from omphalos.isotopes import add_isotope_reactions

        _, needs_name = add_isotope_reactions(
            stripped_namelist, 'S', '34', {'SO4--': 'S34O4--'})

        assert 'Sulfate_reduction' in needs_name

    def test_a_given_reaction_name_is_used(self, stripped_namelist):
        from omphalos.isotopes import add_isotope_reactions

        added, needs_name = add_isotope_reactions(
            stripped_namelist, 'S', '34', {'SO4--': 'S34O4--'},
            names={'Sulfate_reduction': 'Sulfate34_reduction'})

        assert not needs_name
        assert any('Sulfate34_reduction' in name for name in added)

    def test_a_prefixed_species_is_relabelled(self, stripped_namelist):
        # Rate dependences name species as 'tot_CrO4--'.
        from omphalos.isotopes import add_isotope_reactions

        add_isotope_reactions(stripped_namelist, 'Cr', '53', self.LABELLED)
        kinetics = next(e for e in stripped_namelist.namelist['aqueouskinetics']
                        if e['name'] == 'Cr53_Fe_redox')

        assert 'tot_Cr53O4--' in kinetics['dependence']
        assert 'tot_CrO4--' not in kinetics['dependence']

    def test_rates_are_copied_unchanged(self, stripped_namelist):
        # Kinetic fractionation lives in the deck's AQUEOUS_KINETICS rates, not here.
        from omphalos.isotopes import add_isotope_reactions

        add_isotope_reactions(stripped_namelist, 'Cr', '53', self.LABELLED)
        entries = {e['name']: e for e in stripped_namelist.namelist['aqueouskinetics']}

        assert entries['Cr53_Fe_redox']['rate25c'] == entries['Cr_Fe_redox']['rate25c']

    def test_keq_offset_applies_equilibrium_fractionation(self, stripped_namelist):
        from omphalos.isotopes import add_isotope_reactions

        add_isotope_reactions(stripped_namelist, 'Cr', '53', self.LABELLED, keq_offset=-0.01)
        entries = {e['name']: e for e in stripped_namelist.namelist['aqueous']}

        assert entries['Cr53_Fe_redox']['keq'] == pytest.approx(
            entries['Cr_Fe_redox']['keq'] - 0.01)

    def test_a_reaction_naming_nothing_labelled_is_left_alone(self, stripped_namelist):
        from omphalos.isotopes import add_isotope_reactions

        added, _ = add_isotope_reactions(stripped_namelist, 'Cr', '53', self.LABELLED)

        assert not any('C5H7O2N_RCH2_Ace_NH4_SR' in name for name in added)

    def test_a_reaction_already_labelled_is_not_duplicated(self, original_namelist):
        from omphalos.isotopes import add_isotope_reactions

        before = len(original_namelist.namelist['aqueous'])
        added, _ = add_isotope_reactions(original_namelist, 'Cr', '53', self.LABELLED)

        assert not added
        assert len(original_namelist.namelist['aqueous']) == before

    def test_no_namelist_is_not_an_error(self):
        from omphalos.isotopes import add_isotope_reactions

        assert add_isotope_reactions(None, 'Cr', '53', self.LABELLED) == ([], [])

    def test_the_result_round_trips_through_f90nml(self, stripped_namelist, tmp_path):
        from omphalos.isotopes import add_isotope_reactions
        from omphalos.namelist import CrunchNameList

        add_isotope_reactions(stripped_namelist, 'Cr', '53', self.LABELLED)
        out = tmp_path / 'written.dbs'
        stripped_namelist.print(str(out))

        names = [e['name'] for e in CrunchNameList(str(out)).namelist['aqueous']]
        assert 'Cr53_Fe_redox' in names


class TestSingleOccurrenceGroups:
    """f90nml returns a group's entry directly when it appears once, not a list of one.

    ex9's aqueous database has a single &AqueousKinetics block until an isotope adds a second, and
    iterating that entry yields its keys rather than the entry.
    """

    def _namelist(self, tmp_path, text):
        from omphalos.namelist import CrunchNameList

        path = tmp_path / 'one.dbs'
        path.write_text(text)
        return CrunchNameList(str(path))

    ONE_OF_EACH = """\
&Aqueous
  name          = 'Sulfate_reduction'
  stoichiometry = -0.125 'SO4--'  0.125 'H2S(aq)'
  keq           = 5.577425
/

&AqueousKinetics
  name          = 'Sulfate_reduction'
  type          = 'MonodBiomass'
  rate25C       = 25000
  monod_terms   = 'tot_SO4--' 5.0E-03
  biomass       = 'C5H7O2NSO4(s)'
/
"""

    def test_a_single_occurrence_group_is_read_as_one_entry(self, tmp_path):
        from omphalos.isotopes import group_entries

        namelist = self._namelist(tmp_path, self.ONE_OF_EACH)
        entries = group_entries(namelist, 'aqueouskinetics')

        assert len(entries) == 1
        assert entries[0]['name'] == 'Sulfate_reduction'

    def test_an_absent_group_is_empty(self, tmp_path):
        from omphalos.isotopes import group_entries

        namelist = self._namelist(tmp_path, self.ONE_OF_EACH)

        assert group_entries(namelist, 'catabolicpathway') == []

    def test_an_isotope_can_be_added_to_a_single_occurrence_group(self, tmp_path):
        from omphalos.isotopes import add_isotope_reactions, group_entries

        namelist = self._namelist(tmp_path, self.ONE_OF_EACH)
        added, _ = add_isotope_reactions(
            namelist, 'S', '34', {'SO4--': 'S34O4--', 'H2S(aq)': 'H2S34(aq)'},
            names={'Sulfate_reduction': 'Sulfate34_reduction'})

        assert len(added) == 2
        names = [e['name'] for e in group_entries(namelist, 'aqueouskinetics')]
        assert names == ['Sulfate_reduction', 'Sulfate34_reduction']

    def test_the_biomass_is_left_alone_when_it_is_not_labelled(self, tmp_path):
        from omphalos.isotopes import add_isotope_reactions, group_entries

        namelist = self._namelist(tmp_path, self.ONE_OF_EACH)
        add_isotope_reactions(namelist, 'S', '34', {'SO4--': 'S34O4--'},
                              names={'Sulfate_reduction': 'Sulfate34_reduction'})
        copy = group_entries(namelist, 'aqueouskinetics')[-1]

        # ex9 labels the sulfate but not the biomass, and that is what its hand-built copy does.
        assert copy['biomass'] == 'C5H7O2NSO4(s)'

    def test_the_biomass_is_relabelled_when_it_is(self, tmp_path):
        from omphalos.isotopes import add_isotope_reactions, group_entries

        namelist = self._namelist(tmp_path, self.ONE_OF_EACH)
        add_isotope_reactions(
            namelist, 'S', '34',
            {'SO4--': 'S34O4--', 'C5H7O2NSO4(s)': 'C5H7O2NS34O4(s)'},
            names={'Sulfate_reduction': 'Sulfate34_reduction'})
        copy = group_entries(namelist, 'aqueouskinetics')[-1]

        assert copy['biomass'] == 'C5H7O2NS34O4(s)'


class TestBiomassInsideAKineticsBlock:
    """A mineral kinetics block can point at another species, which a copy has to follow.

    A BiomassDecay stanza names the biomass it consumes as `biomass = 'C5H7O2NSO4(s)'`. Only quoted
    tokens are relabelled, since the unquoted text in these blocks includes `rate(25C)`.
    """

    def test_a_quoted_species_is_relabelled(self):
        from omphalos.isotopes import relabel_quoted

        line = "  biomass = 'C5H7O2NSO4(s)' /\n"
        assert relabel_quoted(line, {'C5H7O2NSO4(s)': 'C5H7O2NS34O4(s)'}) == (
            "  biomass = 'C5H7O2NS34O4(s)' /\n")

    def test_unquoted_text_is_untouched(self):
        from omphalos.isotopes import relabel_quoted

        # A carbon isotope must not turn this into 'rate(25C13)'.
        line = '  rate(25C) = -6.00   !cis\n'
        assert relabel_quoted(line, {'C': 'C13'}) == line

    def test_an_unlabelled_species_is_left_alone(self):
        from omphalos.isotopes import relabel_quoted

        line = "  biomass = 'C5H7O2NSO4(s)' /\n"
        assert relabel_quoted(line, {'SO4--': 'S34O4--'}) == line


class TestAtomCountsAreCountedAfterwards:
    """The count has to be taken once the labelled set is complete, not as it is built.

    Counting during the walk fixed each species' total from whatever was labelled at the moment it
    was reached, and never revised it -- so a species standing on both the parent and a species
    labelled later came out short, and file order decided whether its weight was right.
    """

    ORDERED = """\
'temperature points' 1   25.
'Debye-Huckel adh'   0.5114
'Debye-Huckel bdh'   0.3288
'Debye-Huckel bdt'   0.0410
'H+' 9.0  1.0    1.0079
'Ca++' 6.0  2.0    40.0780
'End of primary'  0.0  0.0  0.0
'XCaY' 2    1.0000 'Ca++'    1.0000 'YCa'    1.0  3.0  0.0   200.0
'YCa' 1    1.0000 'Ca++'    2.0  3.0  0.0   100.0
'End of secondary' 1 0. '0' 0. 0. 0.
'End of gases' 0. 1 1. '0' 0. 0. 0.
'End of minerals' 0. 1 0. '0' 0. 0. 0.
"""

    @pytest.fixture
    def ordered(self, tmp_path):
        # XCaY stands on Ca++ *and* on YCa, and its row comes first, so when it is reached YCa has
        # not been labelled yet.
        path = tmp_path / 'ordered.dbs'
        path.write_text(self.ORDERED, newline='')
        return Database(str(path))

    def test_a_species_standing_on_a_later_one_is_counted_in_full(self, ordered):
        report = add_isotope(ordered, 'Ca', '44')

        assert report.atoms['YCa'] == pytest.approx(1.0)
        assert report.atoms['XCaY'] == pytest.approx(2.0)

    def test_and_gets_the_weight_that_follows(self, ordered):
        add_isotope(ordered, 'Ca', '44')

        # Ca44 shifts by +4 per atom: one atom for YCa, two for XCaY.
        assert ordered.secondary_species['YCa44'].weight == pytest.approx(104.0)
        assert ordered.secondary_species['XCa44Y'].weight == pytest.approx(208.0)

    def test_nothing_is_left_uncounted(self, ordered):
        report = add_isotope(ordered, 'Ca', '44')

        assert report.uncounted == []

    def test_the_counts_agree_with_a_relaxed_recount_on_the_real_database(self, stripped):
        # The check the audit used: recompute from the finished labelled set and compare.
        from omphalos.isotopes import count_atoms

        database = stripped('Cr53')
        report = add_isotope(database, 'Cr', '53', parents=['CrO4--'])
        recount = count_atoms(Database(str(database.path)), report.labelled, ['CrO4--'])

        for name, atoms in report.atoms.items():
            if name in recount:
                assert atoms == pytest.approx(recount[name]), name


class TestLabelledIsWhatTheDatabaseHolds:
    """A scope means most of the closure was never written, and the namelists must not use it.

    Relabelling a namelist reference to a species the database does not contain gives CrunchTope a
    reaction it cannot resolve.
    """

    def test_only_written_species_are_exposed(self, stripped):
        database = stripped('Cr53')
        report = add_isotope(database, 'Cr', '53', species=['Cr(OH)3'])

        for name, new_name in report.labelled.items():
            assert any(new_name in getattr(database, section) for section in
                       ['primary_species', 'secondary_species', 'gases', 'minerals',
                        'surface_complexation', 'exchange']), f'{new_name} is not in the database'

    def test_a_scoped_out_species_is_not_exposed(self, stripped):
        database = stripped('Cr53')
        report = add_isotope(database, 'Cr', '53', species=['Cr(OH)3'])

        # CrCl++ is in the closure but outside the scope, so nothing may relabel a reference to it.
        assert 'CrCl++' not in report.labelled
        assert 'Cr53Cl++' not in database.secondary_species

    def test_a_namelist_reference_is_left_alone_for_a_scoped_out_species(self, stripped):
        from omphalos.isotopes import relabel_value

        database = stripped('Cr53')
        report = add_isotope(database, 'Cr', '53', species=['Cr(OH)3'])

        assert relabel_value('tot_CrCl++', report.labelled) == 'tot_CrCl++'
        assert relabel_value('tot_CrO4--', report.labelled) == 'tot_Cr53O4--'

    def test_a_species_already_present_still_counts_as_available(self):
        # Not "what this call added": an isotope added by an earlier run is there to be referenced.
        database = Database(str(DB_PATH))
        report = add_isotope(database, 'Cr', '53', species=['Cr(OH)3'])

        assert report.already_present
        assert report.labelled.get('Cr(OH)3') == 'Cr53(OH)3'
