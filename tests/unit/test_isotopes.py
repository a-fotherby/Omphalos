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
        database = stripped('Cr53')
        report = add_isotope(database, 'Cr', '53', mass_shift=1)
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

    def test_no_mass_shift_keeps_the_parents_weight(self, stripped, db):
        database = stripped('Cr53')
        add_isotope(database, 'Cr', '53')

        assert database.secondary_species['Cr53+++'].weight == pytest.approx(
            db.secondary_species['Cr+++'].weight)

    def test_a_mass_shift_is_applied_per_atom(self, stripped, db):
        database = stripped('Cr53')
        add_isotope(database, 'Cr', '53', names={'Cr2O7--': 'Cr53_2O7--'}, mass_shift=1)

        assert database.secondary_species['Cr53+++'].weight == pytest.approx(
            db.secondary_species['Cr+++'].weight + 1)
        assert database.secondary_species['Cr53_2O7--'].weight == pytest.approx(
            db.secondary_species['Cr2O7--'].weight + 2)

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
