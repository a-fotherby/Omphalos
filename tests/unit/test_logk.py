"""Unit tests for omphalos/logk.py.

The pure reconciliation logic is tested without pyGCC, since a log K belongs to a reaction as
written and getting that wrong is the way this feature produces confident nonsense. The tests that
actually call pyGCC skip where it is absent.
"""

from pathlib import Path

import pytest

from omphalos import logk
from omphalos.database import Database, Reaction

DB_PATH = Path(__file__).parent.parent / 'omphalos_test' / 'SukindaCr53.dbs'

# Calcite as both the target database and thermo.2021 write it: Calcite = -1 H+ + Ca++ + HCO3-.
CALCITE = [-1.0, 'H+', 1.0, 'Ca++', 1.0, 'HCO3-']


class TestSignedStoichiometry:
    def test_products_are_positive_and_reactants_negative(self):
        signed = logk.signed_stoichiometry(Reaction('Calcite', CALCITE), 'Calcite')

        assert signed == {'Ca++': 1.0, 'HCO3-': 1.0, 'H+': -1.0}

    def test_the_species_itself_is_excluded(self):
        # It carries a coefficient of 1 on the reactant side in every compilation, so it says
        # nothing about how the reaction is scaled.
        assert 'Calcite' not in logk.signed_stoichiometry(Reaction('Calcite', CALCITE), 'Calcite')


class TestStoichiometryFactor:
    def test_identical_reactions_need_no_conversion(self):
        target = Reaction('Calcite', CALCITE)
        source = Reaction('Calcite', CALCITE)

        assert logk.stoichiometry_factor(target, source, 'Calcite') == pytest.approx(1.0)

    def test_a_reaction_written_backwards_flips_the_sign(self):
        target = Reaction('Calcite', CALCITE)
        source = Reaction('Calcite', [1.0, 'H+', -1.0, 'Ca++', -1.0, 'HCO3-'])

        assert logk.stoichiometry_factor(target, source, 'Calcite') == pytest.approx(-1.0)

    def test_a_scaled_reaction_scales_the_log_k(self):
        target = Reaction('Calcite', [-2.0, 'H+', 2.0, 'Ca++', 2.0, 'HCO3-'])
        source = Reaction('Calcite', CALCITE)

        assert logk.stoichiometry_factor(target, source, 'Calcite') == pytest.approx(2.0)

    def test_a_different_species_set_is_not_a_rescaling(self):
        # A reaction written on a different basis. Its log K means something else entirely.
        target = Reaction('Calcite', CALCITE)
        source = Reaction('Calcite', [-2.0, 'H+', 1.0, 'Ca++', 1.0, 'CO3--'])

        assert logk.stoichiometry_factor(target, source, 'Calcite') is None

    def test_inconsistent_ratios_are_not_a_rescaling(self):
        # Same species, but not the same reaction: one coefficient doubled and another not.
        target = Reaction('Calcite', [-2.0, 'H+', 1.0, 'Ca++', 1.0, 'HCO3-'])
        source = Reaction('Calcite', CALCITE)

        assert logk.stoichiometry_factor(target, source, 'Calcite') is None

    def test_a_reaction_with_no_other_species_is_declined(self):
        assert logk.stoichiometry_factor(
            Reaction('X', []), Reaction('X', []), 'X'
        ) is None


class TestSectionsOffered:
    def test_only_computable_sections_are_offered(self):
        assert set(logk.SECTION_SPECIE_CLASS) == {'minerals', 'secondary_species', 'gases'}

    def test_the_empirical_sections_are_not(self):
        # Exchange coefficients and surface complexation constants are fitted, not computed. A full
        # regeneration would overwrite them with placeholders, which is the whole reason this mode
        # touches log K columns only.
        assert 'exchange' not in logk.SECTION_SPECIE_CLASS
        assert 'surface_complexation' not in logk.SECTION_SPECIE_CLASS


class TestVersionFloor:
    def test_the_floor_is_the_release_that_fixed_numpy_2(self):
        assert logk.MINIMUM_PYGCC == (1, 5, 3)

    def test_an_old_pygcc_is_refused(self, monkeypatch):
        monkeypatch.setattr('importlib.metadata.version', lambda name: '1.5.2')

        with pytest.raises(ImportError, match='1.5.3'):
            logk.check_pygcc_version()

    def test_a_new_enough_pygcc_passes(self, monkeypatch):
        monkeypatch.setattr('importlib.metadata.version', lambda name: '1.6.0')

        assert logk.check_pygcc_version() == '1.6.0'


class TestWithPygcc:
    """Tests that actually call pyGCC."""

    @pytest.fixture(scope='class')
    def calculator(self):
        pytest.importorskip('pygcc', reason='requires pygcc >= 1.5.3')
        return logk.LogKCalculator()

    @pytest.fixture
    def database(self):
        return Database(str(DB_PATH))

    def test_settings_record_what_moves_log_k(self, calculator):
        # Dielec_method, heatcap_method and densityextrap all change the numbers, so a sweep that
        # does not record them is not reproducible.
        assert set(calculator.settings) >= {
            'pygcc', 'sourcedb', 'sourceformat', 'Dielec_method', 'heatcap_method',
            'densityextrap',
        }

    def test_source_reaction_is_read_as_a_reaction(self, calculator):
        reaction = calculator.source_reaction('Calcite')

        assert reaction.products == {'Ca++': pytest.approx(1.0), 'HCO3-': pytest.approx(1.0)}
        assert reaction.reactants['H+'] == pytest.approx(1.0)

    def test_an_absent_reaction_returns_none(self, calculator):
        assert calculator.source_reaction('NotAMineral') is None

    def test_only_log_k_columns_change(self, calculator, database):
        # The decisive test: species names, stoichiometry, molar volumes, Debye-Huckel sizes,
        # charges, weights, the kinetics block and the exchange block must all be byte-identical.
        before = Database(str(DB_PATH))
        calculator.recompute(database, reactions=['Calcite'], on_unmatched='leave')

        changed = [i for i, (a, b) in enumerate(zip(before.lines, database.lines)) if a != b]
        assert changed == [before.minerals['Calcite'].line_index]

        old, new = before.lines[changed[0]].split(), database.lines[changed[0]].split()
        log_k_columns = range(len(old) - 9, len(old) - 1)
        assert [i for i, (a, b) in enumerate(zip(old, new)) if a != b] == list(log_k_columns)

    def test_the_recomputed_values_are_close_to_the_shipped_ones(self, calculator, database):
        # thermo.2021 is where these came from, so a large disagreement means the reaction was
        # matched to the wrong thing or the temperature grid does not line up.
        before = Database(str(DB_PATH))
        calculator.recompute(database, reactions=['Calcite'], on_unmatched='leave')

        assert database.minerals['Calcite'].name == 'Calcite'
        recomputed = [float(v) for v in database.value('minerals', 'Calcite', 'log_k')]
        assert recomputed == pytest.approx(before.minerals['Calcite'].log_k, abs=0.05)

    def test_values_are_written_to_the_database_s_own_precision(self, calculator, database):
        calculator.recompute(database, reactions=['Calcite'], on_unmatched='leave')
        line = database.lines[database.minerals['Calcite'].line_index].split()

        assert all(len(token.split('.')[1]) == logk.LOG_K_DECIMALS
                   for token in line[len(line) - 9:len(line) - 1])

    def test_the_temperature_grid_is_the_target_s_own(self, calculator, database):
        result = calculator.recompute(database, reactions=['Calcite'], on_unmatched='leave')

        assert len(result.updated['minerals/Calcite']) == database.temp_points

    def test_an_unmatched_reaction_is_named_not_silently_left(self, calculator, database):
        result = calculator.recompute(database, reactions=['Goethite'], on_unmatched='leave')

        assert 'minerals/Goethite' in result.unmatched
        assert not result.updated

    def test_on_unmatched_error_refuses_a_partial_update(self, calculator, database):
        with pytest.raises(ValueError, match='kept their existing log K'):
            calculator.recompute(database, reactions=['Goethite'], on_unmatched='error')

    def test_on_unmatched_warn_says_so(self, calculator, database):
        with pytest.warns(UserWarning, match='kept their existing log K'):
            calculator.recompute(database, reactions=['Goethite'], on_unmatched='warn')

    def test_an_alias_maps_a_renamed_reaction(self, calculator, database):
        calculator.aliases = {'Goethite': 'Calcite'}
        try:
            result = calculator.recompute(database, reactions=['Goethite'],
                                          on_unmatched='leave')
        finally:
            calculator.aliases = {}

        # Matched via the alias, then declined because the stoichiometries are different
        # reactions -- which is the safe outcome, not a silent wrong number.
        assert 'minerals/Goethite' not in result.unmatched
        assert 'minerals/Goethite' in result.skipped

    def test_an_empirical_section_is_refused(self, calculator, database):
        with pytest.raises(ValueError, match='fitted, not computed'):
            calculator.recompute(database, sections=['exchange'])

    def test_an_unknown_policy_is_refused(self, calculator, database):
        with pytest.raises(ValueError, match='on_unmatched must be'):
            calculator.recompute(database, reactions=[], on_unmatched='ignore')

    def test_a_recomputed_database_still_round_trips(self, calculator, database, tmp_path):
        calculator.recompute(database, reactions=['Calcite'], on_unmatched='leave')
        out = tmp_path / 'recomputed.dbs'
        database.print(str(out))

        assert Database(str(out)).minerals['Calcite'].log_k == pytest.approx(
            [float(v) for v in database.value('minerals', 'Calcite', 'log_k')]
        )


class TestTemplateWiring:
    """A config asking for a recomputation gets one, once, before any sweep."""

    @pytest.fixture
    def config(self, omphalos_test_dir):
        import yaml
        with open(omphalos_test_dir / 'sukinda_cr.yaml') as file:
            config = yaml.safe_load(file)
        config['number_of_files'] = 2
        return config

    @pytest.fixture
    def in_test_dir(self, omphalos_test_dir):
        import os
        original = os.getcwd()
        os.chdir(omphalos_test_dir)
        try:
            yield omphalos_test_dir
        finally:
            os.chdir(original)

    def _template(self, config, quiet=True):
        import contextlib
        import io
        from omphalos.template import Template
        with contextlib.redirect_stdout(io.StringIO()):
            return Template(config)

    def test_no_database_logk_means_no_recomputation(self, config, in_test_dir):
        config['database_parameters'] = {'exchange': {'CaXRifle': {'log_k': ['constant', -1.0]}}}
        template = self._template(config)

        assert template.recompute_log_k() is None

    def test_database_logk_alone_parses_the_database(self, config, in_test_dir):
        pytest.importorskip('pygcc', reason='requires pygcc >= 1.5.3')
        config['database_logk'] = {'reactions': ['Calcite'], 'on_unmatched': 'leave'}
        template = self._template(config)

        assert template.database is not None
        assert 'minerals/Calcite' in template.recompute_log_k().updated

    def test_the_recomputation_reaches_every_run(self, config, in_test_dir, tmp_path):
        pytest.importorskip('pygcc', reason='requires pygcc >= 1.5.3')
        from omphalos import generate_inputs as gi
        import contextlib
        import io

        config['database_logk'] = {'reactions': ['Calcite'], 'on_unmatched': 'leave'}
        template = self._template(config)
        recomputed = template.database.value('minerals', 'Calcite', 'log_k')

        with contextlib.redirect_stdout(io.StringIO()):
            file_dict = gi.configure_input_files(template, str(tmp_path) + '/', rhea=True)

        for run in file_dict:
            assert file_dict[run].database.value('minerals', 'Calcite', 'log_k') == recomputed

    def test_a_sweep_edits_the_recomputed_database(self, config, in_test_dir, tmp_path):
        pytest.importorskip('pygcc', reason='requires pygcc >= 1.5.3')
        from omphalos import generate_inputs as gi
        import contextlib
        import io

        config['database_logk'] = {'reactions': ['Calcite'], 'on_unmatched': 'leave'}
        config['database_parameters'] = {
            'exchange': {'CaXRifle': {'log_k': ['custom', [-1.2, -0.6]]}}
        }
        template = self._template(config)
        recomputed = template.database.value('minerals', 'Calcite', 'log_k')

        with contextlib.redirect_stdout(io.StringIO()):
            file_dict = gi.configure_input_files(template, str(tmp_path) + '/', rhea=True)

        # The fitted exchange coefficient varies per run; the recomputed log K does not.
        assert [file_dict[r].database.value('exchange', 'CaXRifle', 'log_k')
                for r in file_dict] == pytest.approx([-1.2, -0.6])
        assert all(file_dict[r].database.value('minerals', 'Calcite', 'log_k') == recomputed
                   for r in file_dict)


class TestPressure:
    """Pressure moves log K, and a CrunchTope database has nowhere to record which pressure."""

    @pytest.fixture(scope='class')
    def source(self):
        pytest.importorskip('pygcc', reason='requires pygcc >= 1.5.3')

    def test_default_is_the_saturation_curve(self, source):
        # How a .dbs is conventionally tabulated, and pyGCC's own idiom for it.
        assert logk.LogKCalculator().pressures([0.0, 25.0]) == 'T'

    def test_a_single_pressure_applies_at_every_point(self, source):
        assert logk.LogKCalculator(pressure=500).pressures([0.0, 25.0, 60.0]) == [500.0] * 3

    def test_a_profile_gives_one_pressure_per_point(self, source):
        calculator = logk.LogKCalculator(pressure=[1, 100, 200])

        assert calculator.pressures([0.0, 25.0, 60.0]) == [1.0, 100.0, 200.0]

    def test_a_mismatched_profile_is_refused(self, source):
        calculator = logk.LogKCalculator(pressure=[1, 100])

        with pytest.raises(ValueError, match='8 temperature points'):
            calculator.pressures([0.0, 25.0, 60.0, 100.0, 150.0, 200.0, 250.0, 300.0])

    def test_the_pressure_is_recorded(self, source):
        # The database cannot carry it: a .dbs header has temperature points and Debye-Huckel
        # coefficients and no pressure row, so a file computed at depth is indistinguishable.
        assert logk.LogKCalculator(pressure=500).settings['pressure'] == 500
        assert logk.LogKCalculator().settings['pressure'] == 'saturation'

    def test_pressure_changes_the_log_k(self, source):
        at_saturation = Database(str(DB_PATH))
        at_depth = Database(str(DB_PATH))

        logk.LogKCalculator().recompute(
            at_saturation, reactions=['Calcite'], on_unmatched='leave')
        logk.LogKCalculator(pressure=500.0).recompute(
            at_depth, reactions=['Calcite'], on_unmatched='leave')

        shallow = [float(v) for v in at_saturation.value('minerals', 'Calcite', 'log_k')]
        deep = [float(v) for v in at_depth.value('minerals', 'Calcite', 'log_k')]

        assert deep != shallow
        # Calcite dissolution, as the database writes it, is favoured by pressure.
        assert all(d > s for d, s in zip(deep, shallow))

    def test_the_cache_is_keyed_on_pressure(self, source):
        # Two calculators differing only in pressure must not share a cached vector.
        database = Database(str(DB_PATH))
        calculator = logk.LogKCalculator()
        temperatures = tuple(float(t) for t in database.temp_field)

        shallow = calculator.log_k('Calcite', 'minerals', temperatures)
        calculator.pressure = 500.0
        deep = calculator.log_k('Calcite', 'minerals', temperatures)

        assert deep != shallow


class TestNoDataSubstitution:
    """pyGCC returns NaN where the water is not liquid; NaN must never reach the file."""

    @pytest.fixture(scope='class')
    def source(self):
        pytest.importorskip('pygcc', reason='requires pygcc >= 1.5.3')

    @pytest.fixture
    def at_one_bar(self, source):
        # 1 bar at every point is below saturation above 100 C, so the Born functions fail there.
        database = Database(str(DB_PATH))
        with pytest.warns(UserWarning):
            result = logk.LogKCalculator(pressure=1.0).recompute(
                database, reactions=['Calcite'], on_unmatched='leave')
        return database, result

    def test_the_sentinel_is_the_databases_own_no_data_value(self):
        assert logk.NO_DATA == 500.0

    def test_no_nan_reaches_the_file(self, at_one_bar):
        database, _ = at_one_bar
        line = database.lines[database.minerals['Calcite'].line_index]

        assert 'nan' not in line.lower()

    def test_the_uncomputable_points_become_the_sentinel(self, at_one_bar):
        database, _ = at_one_bar
        values = [float(v) for v in database.value('minerals', 'Calcite', 'log_k')]

        assert values[-5:] == pytest.approx([logk.NO_DATA] * 5)
        assert values[0] != logk.NO_DATA, 'the points that did compute are kept'

    def test_the_substitutions_are_counted(self, at_one_bar):
        _, result = at_one_bar

        assert result.no_data['minerals/Calcite'] == 5
        assert result.counts['no_data'] == 1

    def test_the_substitution_is_warned_about(self, source):
        database = Database(str(DB_PATH))

        with pytest.warns(UserWarning, match='could not be computed'):
            logk.LogKCalculator(pressure=1.0).recompute(
                database, reactions=['Calcite'], on_unmatched='leave')

    def test_the_summary_says_so(self, at_one_bar):
        _, result = at_one_bar

        assert 'could not be computed' in result.summary()

    def test_a_saturation_run_substitutes_nothing(self, source):
        database = Database(str(DB_PATH))
        result = logk.LogKCalculator().recompute(
            database, reactions=['Calcite'], on_unmatched='leave')

        assert not result.no_data


class TestCacheIsNotProcessWide:
    def test_the_cache_lives_on_the_calculator(self):
        pytest.importorskip('pygcc', reason='requires pygcc >= 1.5.3')
        first = logk.LogKCalculator()
        second = logk.LogKCalculator()

        assert first.cache is not second.cache
        assert first.cache == {}


class TestLaterInputFilesDoNotReparse:
    """A later input file writes no database, so parsing one for it is pure cost."""

    def test_the_database_is_parsed_once_for_the_whole_template_tree(self, monkeypatch, tmp_path):
        import contextlib
        import io
        import os

        import omphalos.database as database_module
        from omphalos.template import Template

        monkeypatch.chdir(tmp_path)

        # Build a two-file chain from the test deck by naming a copy as a later input.
        test_dir = Path(__file__).parent.parent / 'omphalos_test'
        for name in ('sukinda_column.in', 'SukindaCr53.dbs', 'aqueous.dbs',
                     'CatabolicPathways.in'):
            (tmp_path / name).write_bytes((test_dir / name).read_bytes())
        deck = (tmp_path / 'sukinda_column.in').read_text()
        (tmp_path / 'later.in').write_text(deck)
        (tmp_path / 'sukinda_column.in').write_text(
            deck.replace('database                SukindaCr53.dbs',
                         'database                SukindaCr53.dbs\n'
                         'later_inputfiles        later.in'))

        parses = []
        original = database_module.Database.parse

        def counting(self, path, lines):
            parses.append(path)
            return original(self, path, lines)

        monkeypatch.setattr(database_module.Database, 'parse', counting)

        config = {
            'template': 'sukinda_column.in',
            'database': 'SukindaCr53.dbs',
            'aqueous_database': None,
            'catabolic_pathways': None,
            'timeout': 60,
            'nodes': 1,
            'conditions': None,
            'number_of_files': 1,
            'database_parameters': {'exchange': {'CaXRifle': {'log_k': ['constant', -1.0]}}},
        }

        with contextlib.redirect_stdout(io.StringIO()):
            template = Template(config)

        assert list(template.later_inputs) == ['later.in']
        assert len(parses) == 1, f'parsed {len(parses)} times for one template tree'
        assert template.later_inputs['later.in'].database is None
        assert template.database is not None


class TestResample:
    """Putting a tabulated vector onto a different grid, without believing the sentinels."""

    GRID = [0.0, 25.0, 60.0, 100.0]

    def test_the_existing_points_come_back_unchanged(self):
        values, _ = logk.resample(self.GRID, self.GRID, [1.0, 2.0, 4.0, 8.0])

        assert values == pytest.approx([1.0, 2.0, 4.0, 8.0])

    def test_a_point_between_two_is_interpolated(self):
        values, _ = logk.resample([12.5], [0.0, 25.0], [0.0, 10.0])

        assert values == pytest.approx([5.0])

    def test_the_no_data_sentinel_is_not_a_value(self):
        # Interpolating through 500 would poison both neighbours.
        values, _ = logk.resample([12.5], self.GRID, [1.0, logk.NO_DATA, 3.0, 4.0])

        assert values[0] < 3.0, 'the 500 was treated as a real point'

    def test_a_single_real_point_becomes_a_constant(self):
        values, _ = logk.resample(self.GRID, self.GRID,
                                  [logk.NO_DATA, 8.82, logk.NO_DATA, logk.NO_DATA])

        assert values == pytest.approx([8.82] * 4)

    def test_all_sentinel_stays_all_sentinel(self):
        values, _ = logk.resample(self.GRID, self.GRID, [logk.NO_DATA] * 4)

        assert values == pytest.approx([logk.NO_DATA] * 4)

    def test_outside_the_range_the_nearest_value_is_held(self):
        # A SUPCRT fit says nothing about temperatures it was never given.
        values, clamped = logk.resample([-50.0, 400.0], [0.0, 25.0], [1.0, 2.0])

        assert values == pytest.approx([1.0, 2.0])
        assert clamped == 2

    def test_inside_the_range_nothing_is_clamped(self):
        _, clamped = logk.resample([10.0], [0.0, 25.0], [1.0, 2.0])

        assert clamped == 0


class TestRegridGuards:
    """CrunchTope's limits are compiled in, so they are worth stating before writing a file."""

    @pytest.fixture(scope='class')
    def calculator(self):
        pytest.importorskip('pygcc', reason='requires pygcc >= 1.5.3')
        return logk.LogKCalculator()

    def test_the_ceiling_is_crunchtopes_own(self):
        assert logk.MAX_TEMPERATURE_POINTS == 8

    def test_more_points_than_crunchtope_holds_is_refused(self, calculator):
        with pytest.raises(ValueError, match='ntmp in params.F90'):
            calculator.regrid(Database(str(DB_PATH)), list(range(9)))

    def test_an_empty_grid_is_refused(self, calculator):
        with pytest.raises(ValueError, match='at least one temperature point'):
            calculator.regrid(Database(str(DB_PATH)), [])

    @pytest.mark.parametrize('count', [2, 3, 4])
    def test_too_few_points_for_the_fit_warns(self, calculator, count):
        # nbasis = 5 in database.F90, so 2-4 points leave the log K fit underdetermined.
        with pytest.warns(UserWarning, match='underdetermined'):
            calculator.regrid(Database(str(DB_PATH)), [float(t) for t in range(count)],
                              reactions=[])

    def test_one_point_does_not_warn(self, calculator, recwarn):
        # ntemp == 1 is branched out as isothermal and needs no fit.
        calculator.regrid(Database(str(DB_PATH)), [25.0], reactions=[])

        assert not [w for w in recwarn if 'underdetermined' in str(w.message)]


class TestRegrid:
    @pytest.fixture(scope='class')
    def regridded(self):
        pytest.importorskip('pygcc', reason='requires pygcc >= 1.5.3')
        database = Database(str(DB_PATH))
        result = logk.LogKCalculator().regrid(
            database, [0.0, 5.0, 10.0, 15.0, 25.0], reactions=['Calcite'])
        return database, result

    def test_the_header_carries_the_new_grid(self, regridded):
        database, _ = regridded

        assert database.temp_points == 5
        assert database.temp_field == pytest.approx([0.0, 5.0, 10.0, 15.0, 25.0])

    @pytest.mark.parametrize('section', logk.GRIDDED_SECTIONS)
    def test_every_row_in_a_gridded_section_is_rebuilt(self, regridded, section):
        # A file with rows of two different widths is not a database, so 'reactions' selects what
        # pyGCC is asked for, never what gets rewritten.
        database, _ = regridded
        widths = {len(entry.log_k) for entry in getattr(database, section).values()}

        assert widths == {5}

    def test_the_requested_reaction_is_recomputed(self, regridded):
        database, result = regridded

        assert 'minerals/Calcite' in result.recomputed
        # Same endpoints as an 8-point recomputation of the same reaction.
        assert database.minerals['Calcite'].log_k[0] == pytest.approx(2.2254, abs=0.001)
        assert database.minerals['Calcite'].log_k[-1] == pytest.approx(1.8481, abs=0.001)

    def test_the_rest_are_resampled_from_their_own_curve(self, regridded):
        _, result = regridded

        assert 'minerals/Quartz' in result.resampled
        assert len(result.resampled) > 2000

    def test_the_debye_huckel_rows_follow(self, regridded):
        # Resampled from the database's own, not recomputed: pyGCC's B-dot follows a different
        # correlation, and regridding a database should not change its activity model.
        database, _ = regridded
        adh = database.dh_params[0][1:]

        assert len(adh) == 5
        assert adh[0] == pytest.approx(0.4939, abs=0.0001)
        assert adh[-1] == pytest.approx(0.5114, abs=0.0001)

    def test_the_sections_without_a_grid_are_untouched(self, regridded):
        database, _ = regridded

        assert database.exchange['CaXRifle'].log_k == pytest.approx(-0.9)
        assert database.mineral_kinetics['Calcite&default'].rate == pytest.approx(-6.19)
        assert database.surface_complexation_parameters['>FeOH_weak'].charge == pytest.approx(0.0)

    def test_the_result_round_trips(self, regridded, tmp_path):
        database, _ = regridded
        out = tmp_path / 'regridded.dbs'
        database.print(str(out))
        reread = Database(str(out))

        assert reread.temp_points == 5
        assert reread.minerals['Calcite'].log_k == pytest.approx(
            database.minerals['Calcite'].log_k)

    def test_it_is_still_editable_afterwards(self, regridded, tmp_path):
        database, _ = regridded
        out = tmp_path / 'regridded.dbs'
        database.print(str(out))
        reread = Database(str(out))
        reread.modify('minerals', 'Calcite', 'log_k', 1.0)

        assert reread.value('minerals', 'Calcite', 'log_k') == pytest.approx([1.0] * 5)


class TestWaterPropertiesAreShared:
    """The water equation of state is solved once per grid, not once per reaction.

    pyGCC recomputes density, dielectric constant and the Gibbs energy of water inside every
    calcRxnlogK call unless they are passed in, and that is nearly the whole cost of a call. Its
    own writers pass them, which is why generating a database takes a second while calling it per
    reaction took half a second each.
    """

    @pytest.fixture
    def calculator(self):
        pytest.importorskip('pygcc', reason='requires pygcc >= 1.5.3')
        return logk.LogKCalculator()

    GRID = (0.0, 25.0, 60.0, 100.0, 150.0, 200.0, 250.0, 300.0)

    def test_the_properties_are_computed_once_per_grid(self, calculator):
        pressures, rhoEG = calculator.water_properties(self.GRID, 'T')

        assert set(rhoEG) == {'rho', 'E', 'dGH2O'}
        assert len(pressures) == len(self.GRID)
        assert calculator.water_properties(self.GRID, 'T')[1] is rhoEG, 'recomputed'

    def test_the_saturation_curve_is_resolved_to_numbers(self, calculator):
        pressures, _ = calculator.water_properties(self.GRID, 'T')

        # The water saturation curve: 0.006 bar at 0 C, 1 atm at 100 C by definition, 86 bar at
        # 300 C. Monotonic throughout.
        assert pressures[0] == pytest.approx(0.006, abs=0.002)
        assert pressures[3] == pytest.approx(1.014, abs=0.01)
        assert pressures[-1] == pytest.approx(85.9, abs=1.0)
        assert list(pressures) == sorted(pressures)

    def test_a_stated_pressure_is_used_as_given(self, calculator):
        pressures, _ = calculator.water_properties(self.GRID, (500.0,) * 8)

        assert list(pressures) == pytest.approx([500.0] * 8)

    def test_different_grids_do_not_share_properties(self, calculator):
        _, first = calculator.water_properties(self.GRID, 'T')
        _, second = calculator.water_properties((0.0, 25.0), 'T')

        assert first is not second

    def test_the_answer_is_unchanged(self, calculator):
        # The whole point: faster, not different.
        values = calculator.log_k('Calcite', 'minerals', self.GRID)

        assert values == pytest.approx(
            [2.2254, 1.8481, 1.3325, 0.7738, 0.0992, -0.5848, -1.3278, -2.2174], abs=0.0001
        )

    def test_a_whole_database_recompute_is_quick(self, calculator):
        # Was ~0.46 s a reaction, so ~20 minutes for a database. Generous bound against a
        # regression that reintroduces the per-call water solve.
        import time

        database = Database(str(DB_PATH))
        start = time.time()
        result = calculator.recompute(database, on_unmatched='leave')
        elapsed = time.time() - start

        assert len(result.updated) > 500, 'nothing was actually computed'
        assert elapsed < 60, f'a whole-database recompute took {elapsed:.0f} s'


class TestSweepSpecRecognition:
    """Telling a sweep apart from a plain setting, which share one namespace in database_logk."""

    def test_a_method_and_params_is_a_sweep(self):
        from omphalos.generate_inputs import is_sweep_spec

        assert is_sweep_spec(['custom', [200.0, 500.0]])

    def test_a_list_of_reaction_names_is_not(self):
        from omphalos.generate_inputs import is_sweep_spec

        assert not is_sweep_spec(['Calcite', 'Quartz'])

    def test_a_pressure_profile_is_not(self):
        # One pressure per temperature point is a documented plain setting, not a sweep.
        from omphalos.generate_inputs import is_sweep_spec

        assert not is_sweep_spec([1.0, 500.0])

    def test_a_scalar_is_not(self):
        from omphalos.generate_inputs import is_sweep_spec

        assert not is_sweep_spec(500)

    def test_an_unknown_method_name_is_not(self):
        from omphalos.generate_inputs import is_sweep_spec

        assert not is_sweep_spec(['nonsense', [1.0, 2.0]])

    def test_a_coverage_setting_is_never_a_sweep(self):
        # 'constant' is a parameter method, so a two-name reaction list beginning with it would
        # otherwise be read as one -- and the recomputation would silently cover nothing.
        from omphalos.generate_inputs import split_logk_settings

        plain, swept = split_logk_settings({'reactions': ['constant', 'Calcite']})

        assert swept == {}
        assert plain == {'reactions': ['constant', 'Calcite']}

    def test_the_two_are_separated(self):
        from omphalos.generate_inputs import split_logk_settings

        plain, swept = split_logk_settings({
            'reactions': ['Calcite'],
            'on_unmatched': 'leave',
            'pressure': ['custom', [200.0, 500.0]],
        })

        assert plain == {'reactions': ['Calcite'], 'on_unmatched': 'leave'}
        assert swept == {'pressure': ['custom', [200.0, 500.0]]}


class TestSweptRecomputation:
    """A swept setting -- a pressure series -- recomputes per run instead of once on the template."""

    @pytest.fixture
    def config(self, omphalos_test_dir):
        import yaml
        with open(omphalos_test_dir / 'sukinda_cr.yaml') as file:
            config = yaml.safe_load(file)
        config['number_of_files'] = 2
        config.pop('database_parameters', None)
        config['database_logk'] = {
            'reactions': ['Calcite'],
            'on_unmatched': 'leave',
            # Both above the saturation pressure at 300 C, so no point is left uncomputable.
            'pressure': ['custom', [200.0, 500.0]],
        }
        return config

    @pytest.fixture
    def in_test_dir(self, omphalos_test_dir):
        import os
        original = os.getcwd()
        os.chdir(omphalos_test_dir)
        try:
            yield omphalos_test_dir
        finally:
            os.chdir(original)

    def _template(self, config):
        import contextlib
        import io
        from omphalos.template import Template
        with contextlib.redirect_stdout(io.StringIO()):
            return Template(config)

    def _files(self, template, tmp_path):
        import contextlib
        import io
        from omphalos import generate_inputs as gi
        with contextlib.redirect_stdout(io.StringIO()):
            return gi.configure_input_files(template, str(tmp_path) + '/', rhea=True)

    def test_registered_as_a_sweepable_block(self):
        from omphalos.generate_inputs import CT_IDs

        assert 'database_logk' in CT_IDs

    def test_it_precedes_database_parameters(self):
        # A recomputation rewrites whole log K columns, so it has to run before the surgical edits.
        from omphalos.generate_inputs import CT_IDs

        blocks = list(CT_IDs)

        assert blocks.index('database_logk') < blocks.index('database_parameters')

    def test_evaluate_config_expands_the_sweep(self, config):
        from omphalos import generate_inputs as gi

        evaluated = gi.evaluate_config(config)['database_logk']

        assert evaluated['swept']['pressure'] == pytest.approx([200.0, 500.0])
        assert evaluated['settings'] == {'reactions': ['Calcite'], 'on_unmatched': 'leave'}

    def test_the_template_defers_rather_than_guessing(self, config, in_test_dir):
        # Without this the specification itself reaches pyGCC as a pressure, which is not caught.
        pytest.importorskip('pygcc', reason='requires pygcc >= 1.5.3')
        template = self._template(config)

        assert template.recompute_log_k() is None

    def test_the_template_database_is_left_at_its_tabulated_values(self, config, in_test_dir):
        pytest.importorskip('pygcc', reason='requires pygcc >= 1.5.3')
        original = Database(str(DB_PATH)).value('minerals', 'Calcite', 'log_k')
        template = self._template(config)

        assert template.database.value('minerals', 'Calcite', 'log_k') == original

    def test_each_run_gets_its_own_columns(self, config, in_test_dir, tmp_path):
        pytest.importorskip('pygcc', reason='requires pygcc >= 1.5.3')
        file_dict = self._files(self._template(config), tmp_path)

        shallow = [float(v) for v in file_dict[0].database.value('minerals', 'Calcite', 'log_k')]
        deep = [float(v) for v in file_dict[1].database.value('minerals', 'Calcite', 'log_k')]

        # Calcite dissolution, as the database writes it, is favoured by pressure at every point.
        assert all(d > s for d, s in zip(deep, shallow))

    def test_only_the_recomputed_rows_differ_between_runs(self, config, in_test_dir, tmp_path):
        pytest.importorskip('pygcc', reason='requires pygcc >= 1.5.3')
        file_dict = self._files(self._template(config), tmp_path)

        first, last = file_dict[0].database, file_dict[1].database
        differing = [i for i, (a, b) in enumerate(zip(first.lines, last.lines)) if a != b]

        assert differing == [first.minerals['Calcite'].line_index]

    def test_the_pressure_used_is_recorded_on_the_run(self, config, in_test_dir, tmp_path):
        # The database cannot record it, so this is the only trace of which pressure ran.
        pytest.importorskip('pygcc', reason='requires pygcc >= 1.5.3')
        file_dict = self._files(self._template(config), tmp_path)

        assert [file_dict[run].logk_settings['pressure'] for run in file_dict] == [200.0, 500.0]

    def test_a_run_without_a_sweep_records_nothing(self, config, in_test_dir, tmp_path):
        pytest.importorskip('pygcc', reason='requires pygcc >= 1.5.3')
        config['database_logk']['pressure'] = 500.0
        file_dict = self._files(self._template(config), tmp_path)

        assert all(file_dict[run].logk_settings is None for run in file_dict)

    def test_a_fixed_setting_is_still_done_once_on_the_template(self, config, in_test_dir,
                                                               tmp_path):
        pytest.importorskip('pygcc', reason='requires pygcc >= 1.5.3')
        config['database_logk']['pressure'] = 500.0
        template = self._template(config)
        recomputed = template.database.value('minerals', 'Calcite', 'log_k')
        file_dict = self._files(template, tmp_path)

        assert all(file_dict[run].database.value('minerals', 'Calcite', 'log_k') == recomputed
                   for run in file_dict)

    def test_recompute_log_k_false_suppresses_the_per_run_pass(self, config, in_test_dir, tmp_path):
        # rhea sets this on the Templates it rebuilds from run directories, whose databases already
        # carry their own recomputed columns. Redoing it would repeat the whole calculation.
        pytest.importorskip('pygcc', reason='requires pygcc >= 1.5.3')
        original = Database(str(DB_PATH)).value('minerals', 'Calcite', 'log_k')
        config['recompute_log_k'] = False
        file_dict = self._files(self._template(config), tmp_path)

        assert all(file_dict[run].database.value('minerals', 'Calcite', 'log_k') == original
                   for run in file_dict)
        assert all(file_dict[run].logk_settings is None for run in file_dict)

    def test_a_surgical_edit_wins_over_the_recomputation(self, config, in_test_dir, tmp_path):
        # Both target the same eight tokens. The documented order is recompute, then edit.
        pytest.importorskip('pygcc', reason='requires pygcc >= 1.5.3')
        fixed = [1.0] * 8
        config['database_parameters'] = {
            'minerals': {'Calcite': {'log_k': ['custom', [fixed, fixed]]}}
        }
        file_dict = self._files(self._template(config), tmp_path)

        for run in file_dict:
            values = file_dict[run].database.value('minerals', 'Calcite', 'log_k')
            assert [float(v) for v in values] == pytest.approx(fixed)

    def test_sweeping_without_a_database_fails_loudly(self, config, in_test_dir, tmp_path):
        pytest.importorskip('pygcc', reason='requires pygcc >= 1.5.3')
        from omphalos import generate_inputs as gi

        template = self._template(config)
        for_run = template.make_dict()[0]
        for_run.database = None

        with pytest.raises(ValueError, match="'database_logk' needs a 'database' entry"):
            gi._apply_logk_recomputation(
                for_run, gi.evaluate_config(config)['database_logk'], 0
            )

    def test_a_staged_pressure_is_detected(self, config):
        from omphalos import generate_inputs as gi

        config['database_logk']['pressure'] = ['staged', [[200.0, 200.0], [500.0, 500.0]]]

        assert gi.has_staged_params(config)

    def test_an_unstaged_pressure_is_not(self, config):
        from omphalos import generate_inputs as gi

        assert not gi.has_staged_params(config)


class TestPressureRecordSurvivesTheRun:
    """rhea's worker rebuilds its InputFile from the run directory, so the settings need a file.

    Every other swept value survives because it is written into something the worker re-reads. The
    pressure a database was computed at is in no file, because a CrunchTope database has nowhere to
    put it -- which is the whole reason this record exists.
    """

    @pytest.fixture
    def input_file(self, omphalos_test_dir):
        import contextlib
        import io
        import os

        import yaml

        from omphalos.template import Template

        original = os.getcwd()
        os.chdir(omphalos_test_dir)
        try:
            with open('sukinda_cr.yaml') as file:
                config = yaml.safe_load(file)
            config['number_of_files'] = 1
            config.pop('database_parameters', None)
            with contextlib.redirect_stdout(io.StringIO()):
                yield Template(config).make_dict()[0]
        finally:
            os.chdir(original)

    def test_settings_are_written_beside_the_database(self, input_file, tmp_path):
        import json

        from omphalos import run as run_module

        input_file.logk_settings = {'pressure': 500.0, 'sourcedb': 'thermo.2021'}
        run_module._print_aux_files(input_file, tmp_path)

        with open(tmp_path / run_module.LOGK_RECORD) as record:
            assert json.load(record) == {'pressure': 500.0, 'sourcedb': 'thermo.2021'}

    def test_nothing_is_written_without_a_recomputation(self, input_file, tmp_path):
        from omphalos import run as run_module

        run_module._print_aux_files(input_file, tmp_path)

        assert not (tmp_path / run_module.LOGK_RECORD).exists()

    def test_the_worker_reads_it_back(self, tmp_path):
        import json

        from omphalos import run as run_module
        from rhea.slurm_exec import _restore_logk_record

        with open(tmp_path / run_module.LOGK_RECORD, 'w') as record:
            json.dump({'pressure': 250.0}, record)

        class Rebuilt:
            logk_settings = None

        rebuilt = Rebuilt()
        _restore_logk_record(rebuilt, tmp_path)

        assert rebuilt.logk_settings == {'pressure': 250.0}

    def test_a_run_without_a_record_is_left_alone(self, tmp_path):
        from rhea.slurm_exec import _restore_logk_record

        class Rebuilt:
            logk_settings = None

        rebuilt = Rebuilt()
        _restore_logk_record(rebuilt, tmp_path)

        assert rebuilt.logk_settings is None


class TestSplitCopiesAreRejoined:
    """A recomputation must not separate an isotopologue from its parent.

    pyGCC can compute `H2S(aq)` and has never heard of `H2S34(aq)`, so it moves one side of every
    labelled pair and leaves the other. add_isotope guaranteed the two were identical; the gap that
    opens is an equilibrium fractionation the database never had. Measured before the fix: 0.0015 log
    units at the saturation curve and 0.3342 at 500 bar for H2S(aq)/H2S34(aq).
    """

    PAIRS = [('secondary_species', 'H2S(aq)', 'H2S34(aq)'),
             ('secondary_species', 'CaSO4(aq)', 'CaS34O4(aq)'),
             ('gases', 'H2S(g)', 'H2S34(g)')]

    @pytest.fixture
    def rebuilt(self, tmp_path):
        """The test database with S34 stripped and put back, then re-read from disk.

        Re-read on purpose: nothing the rebuild recorded in memory survives, which is the case a
        database that merely *ships* with isotopes is always in.
        """
        pytest.importorskip('pygcc', reason='requires pygcc >= 1.5.3')
        import io
        import warnings

        from omphalos.isotopes import add_isotope

        with io.open(DB_PATH, newline='') as file:
            lines = file.readlines()
        path = tmp_path / 'no_s34.dbs'
        with io.open(path, 'w', newline='') as file:
            file.writelines(line for line in lines if 'S34' not in line)

        database = Database(str(path))
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            add_isotope(database, 'S', '34', parents=['SO4--', 'HS-'])
        database.print(str(path))

        return path

    def _recompute(self, path, pressure):
        import warnings

        database = Database(str(path))
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            result = logk.LogKCalculator(pressure=pressure).recompute(database,
                                                                      on_unmatched='leave')
        return database, result

    def test_the_pairs_start_identical(self, rebuilt):
        database = Database(str(rebuilt))

        for section, parent, child in self.PAIRS:
            assert (database.value(section, parent, 'log_k')
                    == database.value(section, child, 'log_k')), child

    @pytest.mark.parametrize('pressure', [None, 500.0])
    def test_they_stay_identical_through_a_recomputation(self, rebuilt, pressure):
        database, _ = self._recompute(rebuilt, pressure)

        for section, parent, child in self.PAIRS:
            assert (database.value(section, parent, 'log_k')
                    == database.value(section, child, 'log_k')), f'{child} at {pressure}'

    def test_the_rejoining_is_reported(self, rebuilt):
        _, result = self._recompute(rebuilt, 500.0)

        assert result.isotopes_restored, 'nothing was reported as rejoined'
        assert 'secondary_species/H2S34(aq)' in result.isotopes_restored
        assert 'isotopologue row(s) copied back' in result.summary()

    def test_the_parent_still_moves(self, rebuilt):
        # The point is to keep the pair together, not to freeze it.
        original = Database(str(rebuilt)).value('secondary_species', 'H2S(aq)', 'log_k')
        database, _ = self._recompute(rebuilt, 500.0)

        assert database.value('secondary_species', 'H2S(aq)', 'log_k') != original


class TestSuspectedIsotopePairs:
    """Name-based detection is used to decide what is safe to edit, never to find the split."""

    def test_a_labelled_name_is_suspected(self):
        from omphalos.isotopes import suspected_isotope_pairs

        suspected = suspected_isotope_pairs(Database(str(DB_PATH)))

        assert suspected.get('Cr53O4--') == 'CrO4--'

    def test_h2o2_is_also_suspected_which_is_why_it_only_gates(self):
        # H2O2 looks exactly like a labelled H2O. Acting on names alone would overwrite a real
        # species' log K with an unrelated one's, which is why the split itself is detected by
        # comparing columns before and after instead.
        from omphalos.isotopes import isotope_name

        assert isotope_name('H2O', 'O', '2') == 'H2O2'


class TestTriviallyNamedCopies:
    """A copy named by hand carries no element symbol before its digits.

    `Anhydrite34` is what `names: {Anhydrite: 'Anhydrite34'}` produces, and no name rule can recover
    `Anhydrite` from it — the character before the digits is a lowercase 'e'. So the name heuristic
    cannot protect it, and the mapping add_isotope records has to.
    """

    @pytest.fixture
    def with_named_copy(self, tmp_path):
        pytest.importorskip('pygcc', reason='requires pygcc >= 1.5.3')
        import shutil
        import warnings

        from omphalos.isotopes import add_isotope

        source = Path(__file__).parent.parent.parent / 'omphalos' / 'examples' \
            / 'quartz_pressure_series' / 'datacom.dbs'
        path = tmp_path / 'named.dbs'
        shutil.copy(source, path)

        database = Database(str(path))
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            add_isotope(database, 'S', '34', parents=['SO4--'],
                        species=['Anhydrite'], names={'Anhydrite': 'Anhydrite34'})

        return database, path

    def test_the_name_rule_cannot_recover_the_parent(self, with_named_copy):
        from omphalos.isotopes import suspected_isotope_pairs

        database, _ = with_named_copy

        assert suspected_isotope_pairs(database).get('Anhydrite34') is None

    def test_but_the_recorded_pairs_can(self, with_named_copy):
        database, _ = with_named_copy

        assert database.isotope_pairs.get('Anhydrite') == 'Anhydrite34'

    def test_so_it_is_rejoined_when_the_record_is_there(self, with_named_copy):
        import warnings

        database, _ = with_named_copy

        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            result = logk.LogKCalculator(pressure=1000.0).recompute(database, on_unmatched='leave')

        assert 'minerals/Anhydrite34' in result.isotopes_restored
        assert (database.value('minerals', 'Anhydrite', 'log_k')
                == database.value('minerals', 'Anhydrite34', 'log_k'))

    def test_and_reported_rather_than_silently_split_without_it(self, with_named_copy):
        # A database that merely *ships* with a trivially-named isotopologue: read from disk, nothing
        # recorded. Nothing can safely identify the pair, so it is named for the reader instead.
        import warnings

        database, path = with_named_copy
        database.print(str(path))
        reread = Database(str(path))

        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            result = logk.LogKCalculator(pressure=1000.0).recompute(reread, on_unmatched='leave')

        assert 'minerals/Anhydrite34' in result.split_copies
        assert 'minerals/Anhydrite34' not in result.isotopes_restored
        assert 'WARNING' in result.summary()


class TestRegridConfigSurface:
    """`database_regrid` puts the temperature grid where the rest of the sweep surface is.

    Regridding was API-only, so a low-temperature model — the case it exists for — needed a script.
    """

    @pytest.fixture
    def config(self, omphalos_test_dir):
        import yaml
        with open(omphalos_test_dir / 'sukinda_cr.yaml') as file:
            config = yaml.safe_load(file)
        config['number_of_files'] = 1
        config.pop('database_parameters', None)
        return config

    @pytest.fixture
    def in_test_dir(self, omphalos_test_dir):
        import os
        original = os.getcwd()
        os.chdir(omphalos_test_dir)
        try:
            yield omphalos_test_dir
        finally:
            os.chdir(original)

    def _template(self, config):
        import contextlib
        import io
        import warnings
        from omphalos.template import Template
        with contextlib.redirect_stdout(io.StringIO()), warnings.catch_warnings():
            warnings.simplefilter('ignore')
            return Template(config)

    GRID = [0.0, 5.0, 10.0, 15.0, 25.0]

    def test_no_section_means_no_regrid(self, config, in_test_dir):
        config['database_logk'] = {'reactions': ['Calcite'], 'on_unmatched': 'leave'}
        template = self._template(config)

        assert template.regrid_database() is None

    def test_the_grid_is_rewritten(self, config, in_test_dir):
        pytest.importorskip('pygcc', reason='requires pygcc >= 1.5.3')
        config['database_regrid'] = {'temperatures': self.GRID, 'reactions': ['Calcite']}
        template = self._template(config)

        assert [float(t) for t in template.database.temp_field] == pytest.approx(self.GRID)

    def test_every_gridded_row_matches_the_new_width(self, config, in_test_dir):
        # A file with rows of two widths is not a database.
        pytest.importorskip('pygcc', reason='requires pygcc >= 1.5.3')
        config['database_regrid'] = {'temperatures': self.GRID, 'reactions': ['Calcite']}
        template = self._template(config)

        for section in ('secondary_species', 'gases', 'minerals'):
            for name in list(getattr(template.database, section))[:20]:
                values = template.database.value(section, name, 'log_k')
                assert len(values) == len(self.GRID), f'{section}/{name}'

    def test_a_missing_grid_fails_loudly(self, config, in_test_dir):
        config['database_regrid'] = {'reactions': ['Calcite']}

        with pytest.raises(ValueError, match="needs a 'temperatures' entry"):
            self._template(config)

    def test_it_runs_before_the_recomputation(self, config, in_test_dir):
        # The recomputation edits tokens in place, so it has to see the new grid.
        pytest.importorskip('pygcc', reason='requires pygcc >= 1.5.3')
        config['database_regrid'] = {'temperatures': self.GRID, 'reactions': ['Calcite']}
        config['database_logk'] = {'reactions': ['Calcite'], 'on_unmatched': 'leave'}
        template = self._template(config)

        assert len(template.database.value('minerals', 'Calcite', 'log_k')) == len(self.GRID)

    def test_regridding_needs_a_database(self, config, in_test_dir):
        config['database'] = None
        config['database_regrid'] = {'temperatures': self.GRID}

        with pytest.raises(ValueError, match='database_regrid'):
            self._template(config)


class TestAugmentation:
    """Adding the row a model is missing, rather than regenerating the database around it.

    A full pyGCC regeneration of SukindaCr53.dbs gives a third of the species and none of the custom
    ones, so it discards exactly the fitted values pyGCC cannot compute. This is the alternative.
    """

    SHIPPED = (Path(__file__).parent.parent.parent / 'omphalos' / 'examples'
               / 'quartz_pressure_series' / 'datacom.dbs')

    @pytest.fixture
    def without_anhydrite(self, tmp_path):
        pytest.importorskip('pygcc', reason='requires pygcc >= 1.5.3')
        import io

        path = tmp_path / 'no_anhydrite.dbs'
        with io.open(self.SHIPPED, newline='') as source:
            lines = source.readlines()
        with io.open(path, 'w', newline='') as target:
            target.writelines(line for line in lines if not line.startswith("'Anhydrite'"))

        return path

    def _add(self, path, sections, **kwargs):
        import warnings

        database = Database(str(path))
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            result = logk.LogKCalculator().add_species(database, sections, **kwargs)
        database.print(str(path))

        return Database(str(path)), result

    def test_the_species_is_added(self, without_anhydrite):
        database, result = self._add(without_anhydrite, {'minerals': ['Anhydrite']})

        assert 'Anhydrite' in database.minerals
        assert result.added['minerals'] == ['Anhydrite']

    def test_the_row_matches_the_one_it_replaced(self, without_anhydrite):
        # The strongest check available: the shipped database has this row, so the generated one can
        # be compared against it field by field.
        database, _ = self._add(without_anhydrite, {'minerals': ['Anhydrite']})
        shipped = Database(str(self.SHIPPED))

        built = database.minerals['Anhydrite']
        reference = shipped.minerals['Anhydrite']

        assert built.molar_volume == pytest.approx(reference.molar_volume)
        assert built.weight == pytest.approx(reference.weight)
        assert built.reaction.products == reference.reaction.products
        assert built.reaction.reactants == reference.reaction.reactants

    def test_the_log_k_agrees_with_the_shipped_column(self, without_anhydrite):
        database, _ = self._add(without_anhydrite, {'minerals': ['Anhydrite']})
        shipped = Database(str(self.SHIPPED))

        built = [float(v) for v in database.value('minerals', 'Anhydrite', 'log_k')]
        reference = [float(v) for v in shipped.value('minerals', 'Anhydrite', 'log_k')]

        # The same agreement the plan records for pyGCC against this compilation.
        assert built == pytest.approx(reference, abs=0.008)

    def test_the_column_width_matches_the_grid(self, without_anhydrite):
        database, _ = self._add(without_anhydrite, {'minerals': ['Anhydrite']})

        assert (len(database.value('minerals', 'Anhydrite', 'log_k'))
                == len(database.temp_field))

    def test_nothing_else_changes(self, without_anhydrite):
        import io

        before = io.open(without_anhydrite, newline='').readlines()
        self._add(without_anhydrite, {'minerals': ['Anhydrite']})
        after = io.open(without_anhydrite, newline='').readlines()

        added = [line for line in after if line not in before]
        assert len(added) == 1 and added[0].startswith("'Anhydrite'")

    def test_a_species_already_there_is_left_alone(self, without_anhydrite):
        _, result = self._add(without_anhydrite, {'secondary_species': ['CaSO4(aq)']})

        assert result.already_present == ['CaSO4(aq)']
        assert not result.added

    def test_an_unknown_species_is_reported(self, without_anhydrite):
        _, result = self._add(without_anhydrite, {'minerals': ['NotAMineral']},
                              on_unknown='leave')

        assert result.unknown == ['NotAMineral']

    def test_an_unknown_species_can_be_fatal(self, without_anhydrite):
        with pytest.raises(ValueError, match='not in the source compilation'):
            self._add(without_anhydrite, {'minerals': ['NotAMineral']}, on_unknown='error')

    def test_a_section_without_a_log_k_is_refused(self, without_anhydrite):
        # Exchange and surface complexation parameters are not species with a log K column.
        with pytest.raises(ValueError, match='cannot be added to'):
            self._add(without_anhydrite, {'exchange': ['NaX']})
