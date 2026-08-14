"""Unit tests for omphalos/database.py."""

import copy
from pathlib import Path

import pytest

from omphalos.database import Database, ExchangeSpecies, Reaction, Species, tokenise

DB_PATH = Path(__file__).parent.parent / 'omphalos_test' / 'SukindaCr53.dbs'
ALT_DB_PATH = Path(__file__).parent.parent.parent / 'omphalos' / 'test_database.dbs'

# A database with three temperature points rather than the usual eight, and LF rather than CRLF
# terminators. Both are legal, and both used to be assumed away.
THREE_POINT_DATABASE = """\
'temperature points' 3   0.  25.  60.
'Debye-Huckel adh'   0.4939  0.5114 0.5465
'Debye-Huckel bdh'   0.3253  0.3288 0.3346
'Debye-Huckel bdt'   0.0374  0.0410 0.0440
'H+' 9.0  1.0    1.0079
'End of primary'  0.0  0.0  0.0
'OH-' 2   -1.0000 'H+'    1.0000 'H2O'   14.9398   13.9951   13.0272  3.5 -1.0   17.0073
'End of secondary' 1 0. '0' 0. 0. 0.
'CO2(g)'    0.0000  2   -1.0000 'H+'    1.0000 'HCO3-'   -7.6765   -7.8136   -8.0527   44.0098
'End of gases' 0. 1 1. '0' 0. 0. 0.
'Calcite'   36.9340  2   -1.0000 'H+'    1.0000 'Ca++'    2.2257    1.8487    1.3330  100.0872
'End of minerals' 0. 1 0. '0' 0. 0. 0.
Begin exchange
'CaX' 2  1.0 'Ca++' 2.0 'X-'          -0.9   0.0000
End of exchange
"""


@pytest.fixture(scope='module')
def db():
    return Database(str(DB_PATH))


@pytest.fixture
def three_point_db(tmp_path):
    path = tmp_path / 'three_points.dbs'
    path.write_text(THREE_POINT_DATABASE, newline='')
    return Database(str(path))


class TestTokenise:
    def test_quoted_names_survive_internal_spaces(self):
        assert tokenise("'Debye-Huckel adh' 0.4939")[0][0] == 'Debye-Huckel adh'

    def test_unquoted_numbers_become_floats(self):
        assert tokenise("'H+' 9.0 1.0")[1][0] == pytest.approx(9.0)

    def test_quoted_tokens_are_never_numbers(self):
        # A quoted token is a name even when it looks like a number.
        assert tokenise("'End of secondary' 1 0. '0' 0.")[3][0] == '0'

    def test_comment_and_everything_after_it_is_dropped(self):
        assert [value for value, _, _ in tokenise('  rate(25C) = -6.00   !cis and more')] == [
            'rate(25C)', '=', -6.0
        ]

    def test_spans_locate_the_token_in_the_line(self):
        line = "'Calcite'   36.9340  3\r\n"
        _, start, end = tokenise(line)[1]
        assert line[start:end] == '36.9340'


class TestRoundTrip:
    """An unedited parse/re-print must be byte-identical. Everything else rests on this."""

    @pytest.mark.parametrize('source', [DB_PATH, ALT_DB_PATH])
    def test_round_trip_is_byte_identical(self, source, tmp_path):
        out = tmp_path / 'round_trip.dbs'
        Database(str(source)).print(str(out))
        assert out.read_bytes() == source.read_bytes()

    def test_crlf_terminators_are_preserved(self, db):
        assert all(line.endswith('\r\n') for line in db.lines[:-1])

    def test_lf_terminators_are_preserved(self, three_point_db, tmp_path):
        out = tmp_path / 'lf.dbs'
        three_point_db.print(str(out))
        assert out.read_bytes() == THREE_POINT_DATABASE.encode()


class TestSections:
    def test_all_sections_found(self, db):
        assert set(db.sections) == {
            'primary', 'secondary', 'gases', 'minerals', 'surface complexation',
            'aqueous kinetics', 'mineral kinetics', 'exchange',
            'surface complexation parameters',
        }

    def test_sections_do_not_overlap(self, db):
        bounds = sorted(db.sections.values())
        assert all(end <= next_start for (_, end), (next_start, _) in zip(bounds, bounds[1:]))

    def test_absent_section_is_simply_missing(self):
        # test_database.dbs has no in-database aqueous kinetics block; the sections either side of
        # where it would sit must not absorb it.
        other = Database(str(ALT_DB_PATH))
        assert 'aqueous kinetics' not in other.sections
        assert other.aqueous_kinetics == {}

    def test_aqueous_kinetics_is_not_the_exchange_block(self, db):
        # These were the same attribute before, and the exchange block had no home of its own.
        assert 'Sulfate_reduction' in db.aqueous_kinetics
        assert 'CaXRifle' in db.exchange

    def test_mineral_kinetics_excludes_aqueous_kinetics(self, db):
        assert 'Sulfate_reduction' not in db.mineral_kinetics
        assert not any(key.startswith('Sulfate_reduction') for key in db.mineral_kinetics)


class TestSpecies:
    def test_species_attributes(self, db):
        fe = db.primary_species['Fe++']
        assert fe.name == 'Fe++'
        assert fe.charge == pytest.approx(2.0)
        assert fe.dh_size == pytest.approx(6.0)
        assert fe.weight == pytest.approx(55.847, abs=0.01)

    def test_h_plus_charge(self, db):
        h = db.primary_species['H+']
        assert h.charge == pytest.approx(1.0)

    def test_secondary_species_trailing_columns(self, db):
        oh = db.secondary_species['OH-']
        assert oh.dh_size == pytest.approx(3.5)
        assert oh.charge == pytest.approx(-1.0)
        assert oh.weight == pytest.approx(17.0073)

    def test_secondary_species_log_k(self, db):
        assert db.secondary_species['OH-'].log_k == pytest.approx(
            [14.9398, 13.9951, 13.0272, 12.2551, 11.6308, 11.2836, 11.1675, 11.3002]
        )


class TestReaction:
    def test_calcite_has_expected_reactants(self, db):
        # Calcite: 3 species, -1.0 H+  1.0 Ca++  1.0 HCO3-
        r = db.minerals['Calcite'].reaction
        assert 'Calcite' in r.reactants
        assert 'H+' in r.reactants

    def test_calcite_has_expected_products(self, db):
        r = db.minerals['Calcite'].reaction
        assert 'Ca++' in r.products
        assert 'HCO3-' in r.products

    def test_stoichiometry_is_positive_in_dicts(self, db):
        r = db.minerals['Calcite'].reaction
        for coeff in r.reactants.values():
            assert coeff > 0
        for coeff in r.products.values():
            assert coeff > 0

    def test_odd_reaction_array_raises(self):
        with pytest.raises(Exception, match="Unpaired"):
            Reaction('Test', [-1.0, 'H+', 1.0])

    def test_zero_stoichiometry_raises(self):
        with pytest.raises(Exception, match="Stoichiometric coefficient = 0"):
            Reaction('Test', [0.0, 'H+', 1.0, 'Ca++'])


class TestMineral:
    def test_goethite_molar_volume(self, db):
        goethite = db.minerals['Goethite']
        assert goethite.molar_volume == pytest.approx(20.82, abs=0.01)

    def test_mineral_log_k_is_the_whole_row(self, db):
        # Read straight off the Calcite row. The slice used to start one column early, so the
        # first 'log K' was the last species name in the reaction.
        assert db.minerals['Calcite'].log_k == pytest.approx(
            [2.2257, 1.8487, 1.3330, 0.7743, 0.0999, -0.5838, -1.3262, -2.2154]
        )

    def test_mineral_weight_follows_the_log_k_columns(self, db):
        assert db.minerals['Calcite'].weight == pytest.approx(100.0872)

    def test_mineral_reaction_type(self, db):
        assert isinstance(db.minerals['Calcite'].reaction, Reaction)

    def test_duplicated_rows_are_exact_copies(self, db):
        # They are copy-paste artefacts, not competing entries, so first-wins loses nothing.
        for name, copies in db.duplicates.items():
            original = db.lines[db.minerals[name].line_index].split()
            assert all(db.lines[index].split() == original for index in copies)

    def test_editing_a_duplicated_name_warns(self):
        database = Database(str(DB_PATH))
        with pytest.warns(UserWarning, match='appears more than once'):
            database.modify('minerals', 'Goethite', 'weight', 88.9)

    def test_first_of_a_duplicated_name_wins(self, db):
        # CrunchTope scans the section forward and uses the first match, so editing any later row
        # of the same name would change a line the simulation ignores.
        assert 'Goethite' in db.duplicates
        first = min(
            index for index in range(*db.sections['minerals'])
            if tokenise(db.lines[index]) and tokenise(db.lines[index])[0][0] == 'Goethite'
        )
        assert db.minerals['Goethite'].line_index == first


class TestGas:
    def test_gas_weight_follows_the_log_k_columns(self, db):
        assert db.gases['CO2(g)'].weight == pytest.approx(44.0098)

    def test_gas_log_k(self, db):
        assert db.gases['CO2(g)'].log_k == pytest.approx(
            [-7.6765, -7.8136, -8.0527, -8.3574, -8.7692, -9.2165, -9.7202, -10.3393]
        )


class TestTemperaturePoints:
    """Nothing may assume eight temperature points; pyGCC can be asked for any number."""

    def test_temperature_point_count(self, db):
        assert db.temp_points == 8

    def test_temperature_field_length(self, db):
        assert len(db.temp_field) == 8

    def test_three_point_database_is_read(self, three_point_db):
        assert three_point_db.temp_points == 3
        assert three_point_db.temp_field == pytest.approx([0.0, 25.0, 60.0])

    def test_log_k_follows_the_point_count(self, three_point_db):
        assert three_point_db.minerals['Calcite'].log_k == pytest.approx([2.2257, 1.8487, 1.3330])
        assert three_point_db.gases['CO2(g)'].log_k == pytest.approx([-7.6765, -7.8136, -8.0527])
        assert three_point_db.secondary_species['OH-'].log_k == pytest.approx(
            [14.9398, 13.9951, 13.0272]
        )

    def test_trailing_columns_follow_the_point_count(self, three_point_db):
        assert three_point_db.minerals['Calcite'].weight == pytest.approx(100.0872)
        assert three_point_db.gases['CO2(g)'].weight == pytest.approx(44.0098)
        assert three_point_db.secondary_species['OH-'].dh_size == pytest.approx(3.5)


class TestExchange:
    """The headline use case: the coefficients PEST is used to fit."""

    def test_exchange_species_present(self, db):
        assert set(db.exchange) >= {'NaXRifle', 'CaXRifle', 'MgXRifle', 'KXRifle'}

    def test_log_k_is_a_single_value(self, db):
        # read_exchange.F90 reads name, n, (stoich, species) * n, log K, bfit — no temperature
        # dependence, whatever the header says.
        assert db.exchange['CaXRifle'].log_k == pytest.approx(-0.9)

    def test_bfit_is_the_last_column(self, db):
        assert db.exchange['CaXRifle'].bfit == pytest.approx(0.0)

    def test_reaction_is_parsed(self, db):
        reaction = db.exchange['CaXRifle'].reaction
        assert reaction.products == {'Ca++': pytest.approx(1.0), 'XRifle-': pytest.approx(2.0)}

    def test_is_an_exchange_species(self, db):
        assert isinstance(db.exchange['CaXRifle'], ExchangeSpecies)


class TestSurfaceComplexation:
    def test_complexes_are_parsed(self, db):
        assert '>FeO-_str' in db.surface_complexation

    def test_log_k_spans_the_temperature_points(self, db):
        assert len(db.surface_complexation['>FeO-_str'].log_k) == db.temp_points

    def test_parameters_section_holds_site_charges(self, db):
        assert db.surface_complexation_parameters['>FeOH_weak'].charge == pytest.approx(0.0)


class TestMineralKinetics:
    def test_entries_are_keyed_by_mineral_and_label(self, db):
        assert 'Calcite&default' in db.mineral_kinetics

    def test_attributes_are_read(self, db):
        calcite = db.mineral_kinetics['Calcite&default']
        assert calcite.type == 'tst'
        assert calcite.rate == pytest.approx(-6.19)
        assert calcite.activation == pytest.approx(0.0)

    def test_namelist_stanzas_are_recorded_not_mistaken_for_minerals(self, db):
        assert not any(key.startswith('&') for key in db.mineral_kinetics)
        assert db.mineral_kinetics['decay_b_so4(s)&default'].namelists

    def test_separator_lines_are_not_entries(self, db):
        assert not any(key.startswith('+') for key in db.mineral_kinetics)


class TestModify:
    @pytest.fixture
    def edited(self, tmp_path):
        """A database copied, edited and re-read, with the original alongside it."""
        def edit(section, entry, parameter, value, source=DB_PATH):
            database = Database(str(source))
            database.modify(section, entry, parameter, value)
            out = tmp_path / 'edited.dbs'
            database.print(str(out))
            before = Path(source).read_text(newline='').splitlines()
            after = out.read_text(newline='').splitlines()
            changed = [i for i, (a, b) in enumerate(zip(before, after)) if a != b]
            return database, before, after, changed

        return edit

    def test_single_token_edit_changes_exactly_one_line(self, edited):
        _, _, _, changed = edited('exchange', 'CaXRifle', 'log_k', -1.25)
        assert len(changed) == 1

    def test_edit_writes_the_new_value(self, edited):
        database, _, _, _ = edited('exchange', 'CaXRifle', 'log_k', -1.25)
        line_index = database.exchange['CaXRifle'].line_index
        assert database.raw_database[line_index][-2] == pytest.approx(-1.25)

    def test_neighbouring_columns_are_untouched(self, edited):
        _, before, after, changed = edited('exchange', 'CaXRifle', 'log_k', -1.25)
        line = changed[0]
        assert before[line].split()[:6] == after[line].split()[:6]
        assert before[line].split()[-1] == after[line].split()[-1]

    def test_trailing_comment_survives(self, edited):
        _, _, after, changed = edited(
            'mineral_kinetics', 'C5H7O2NFe(s)', 'rate(25C)', -8.5, ALT_DB_PATH
        )
        assert after[changed[0]].endswith('!cis')
        assert '-8.5' in after[changed[0]]

    def test_a_bare_mineral_name_resolves_to_its_rate_law(self, edited):
        _, _, _, changed = edited('mineral_kinetics', 'Calcite', 'rate(25C)', -8.5)
        assert len(changed) == 1

    def test_scalar_fills_every_temperature_point(self, edited):
        database, _, after, changed = edited('minerals', 'Calcite', 'log_k', 1.85)
        assert len(changed) == 1
        assert database.minerals['Calcite'].line_index == changed[0]
        assert after[changed[0]].split().count('1.85') == database.temp_points

    def test_a_vector_sets_each_point(self, edited):
        values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
        _, _, after, changed = edited('minerals', 'Calcite', 'log_k', values)
        assert [float(token) for token in after[changed[0]].split()[-9:-1]] == pytest.approx(values)

    def test_column_width_is_held_where_the_new_value_is_shorter(self, edited):
        _, before, after, changed = edited('minerals', 'Calcite', 'log_k', 1.85)
        assert len(after[changed[0]]) == len(before[changed[0]])

    def test_unedited_database_round_trips_after_a_modify_elsewhere(self, edited):
        _, before, after, _ = edited('exchange', 'CaXRifle', 'log_k', -1.25)
        assert len(before) == len(after)


class TestModifyFailsLoudly:
    """An unrecognised name must not leave the database quietly unedited."""

    def test_unknown_section(self, db):
        with pytest.raises(KeyError, match='not a section'):
            db.modify('not_a_section', 'CaXRifle', 'log_k', 1.0)

    def test_unknown_entry(self, db):
        with pytest.raises(KeyError, match="not in the 'exchange' section"):
            db.modify('exchange', 'NotASpecies', 'log_k', 1.0)

    def test_unknown_parameter(self, db):
        with pytest.raises(KeyError, match='not an editable parameter'):
            db.modify('exchange', 'CaXRifle', 'not_a_parameter', 1.0)

    def test_wrong_number_of_values(self, db):
        with pytest.raises(ValueError, match='spans 8 values'):
            db.modify('minerals', 'Calcite', 'log_k', [1.0, 2.0])


class TestIndex:
    def test_every_section_is_indexed(self, db):
        assert set(db.index) == {
            'primary_species', 'secondary_species', 'gases', 'minerals', 'surface_complexation',
            'aqueous_kinetics', 'mineral_kinetics', 'exchange',
            'surface_complexation_parameters',
        }

    def test_index_points_at_the_entry_line(self, db):
        line_index, token_index = db.index['exchange']['CaXRifle']['log_k']
        assert line_index == db.exchange['CaXRifle'].line_index
        assert tokenise(db.lines[line_index])[token_index][0] == pytest.approx(-0.9)

    def test_species_are_species(self, db):
        assert isinstance(db.primary_species['H+'], Species)


class TestHeaderValidation:
    """A bad header mis-slices every log K in the file, so it has to be caught at the header."""

    def _write(self, tmp_path, text):
        path = tmp_path / 'bad.dbs'
        path.write_text(text, newline='')
        return str(path)

    def test_a_leading_comment_is_refused(self, tmp_path):
        path = self._write(tmp_path, '! a comment\n' + THREE_POINT_DATABASE)

        with pytest.raises(ValueError, match='temperature points'):
            Database(path)

    def test_a_declared_count_must_match_the_temperatures_listed(self, tmp_path):
        path = self._write(tmp_path, THREE_POINT_DATABASE.replace(
            "'temperature points' 3", "'temperature points' 4"))

        with pytest.raises(ValueError, match='declares 4'):
            Database(path)

    def test_a_file_too_short_to_be_a_database_is_refused(self, tmp_path):
        with pytest.raises(ValueError, match='three Debye-Huckel rows'):
            Database(self._write(tmp_path, "'temperature points' 1 25.\n"))


class TestSectionMarkerValidation:
    """A mismatched marker means the section map is wrong, and edits would target the wrong rows."""

    def _write(self, tmp_path, extra):
        path = tmp_path / 'markers.dbs'
        path.write_text(THREE_POINT_DATABASE + extra, newline='')
        return str(path)

    def test_an_unclosed_section_is_refused(self, tmp_path):
        with pytest.raises(ValueError, match='never closes'):
            Database(self._write(tmp_path, 'Begin mineral kinetics\n'))

    def test_a_section_opened_inside_another_is_refused(self, tmp_path):
        with pytest.raises(ValueError, match='still open'):
            Database(self._write(tmp_path, 'Begin exchange\nBegin mineral kinetics\n'))

    def test_a_section_closed_by_the_wrong_name_is_refused(self, tmp_path):
        with pytest.raises(ValueError, match='but the open block'):
            Database(self._write(tmp_path, 'Begin exchange\nEnd of mineral kinetics\n'))


class TestParallelRateLaws:
    """A mineral repeated in the kinetics block is a parallel rate law, not a duplicate.

    read_minkin.F90 loads every occurrence and CrunchTope runs them together, so keeping only one
    would let an edit rewrite one rate law while the simulation runs two.
    """

    def test_distinct_labels_give_distinct_keys(self, db):
        assert {'CalciteRifle&default', 'CalciteRifle&DePaoloDissolution',
                'CalciteRifle&DePaoloPrecip'} <= set(db.mineral_kinetics)

    def test_a_shared_label_keeps_both(self, db):
        assert sorted(k for k in db.mineral_kinetics if k.startswith('Fe(OH)3&')) == [
            'Fe(OH)3&default#1', 'Fe(OH)3&default#2'
        ]

    def test_they_are_different_lines(self, db):
        first = db.mineral_kinetics['Fe(OH)3&default#1'].line_index
        second = db.mineral_kinetics['Fe(OH)3&default#2'].line_index
        assert first != second

    def test_the_bare_mineral_name_refuses_to_guess(self, db):
        with pytest.raises(KeyError, match='matches several'):
            db.modify('mineral_kinetics', 'Fe(OH)3', 'rate(25C)', -9.9)

    def test_the_bare_label_refuses_to_guess(self, db):
        with pytest.raises(KeyError, match='parallel rate laws'):
            db.modify('mineral_kinetics', 'Fe(OH)3&default', 'rate(25C)', -9.9)

    def test_an_explicitly_named_one_is_editable(self, tmp_path):
        database = Database(str(DB_PATH))
        database.modify('mineral_kinetics', 'Fe(OH)3&default#2', 'rate(25C)', -9.9)

        assert database.value('mineral_kinetics', 'Fe(OH)3&default#2', 'rate(25C)') == -9.9
        assert database.value('mineral_kinetics', 'Fe(OH)3&default#1', 'rate(25C)') == -11.25


class TestTheParsedViewFollowsTheEdit:
    """The parse is shared between runs, so it must update without leaking."""

    @pytest.fixture
    def template(self):
        return Database(str(DB_PATH))

    def test_a_scalar_parameter_updates(self, template):
        run = copy.deepcopy(template)
        run.modify('exchange', 'CaXRifle', 'log_k', -1.0)

        assert run.exchange['CaXRifle'].log_k == pytest.approx(-1.0)

    def test_a_vector_parameter_updates(self, template):
        run = copy.deepcopy(template)
        run.modify('minerals', 'Calcite', 'log_k', 3.0)

        assert run.minerals['Calcite'].log_k == pytest.approx([3.0] * 8)

    def test_mineral_kinetics_updates(self, template):
        run = copy.deepcopy(template)
        run.modify('mineral_kinetics', 'Calcite', 'rate(25C)', -8.5)

        assert run.mineral_kinetics['Calcite&default'].rate == pytest.approx(-8.5)

    def test_the_template_is_untouched(self, template):
        run = copy.deepcopy(template)
        run.modify('exchange', 'CaXRifle', 'log_k', -1.0)

        assert template.exchange['CaXRifle'].log_k == pytest.approx(-0.9)

    def test_sibling_runs_are_untouched(self, template):
        first, second = copy.deepcopy(template), copy.deepcopy(template)
        first.modify('exchange', 'CaXRifle', 'log_k', -1.0)
        second.modify('exchange', 'CaXRifle', 'log_k', -2.0)

        assert first.exchange['CaXRifle'].log_k == pytest.approx(-1.0)
        assert second.exchange['CaXRifle'].log_k == pytest.approx(-2.0)

    def test_the_section_dict_is_copied_not_mutated(self, template):
        run = copy.deepcopy(template)
        run.modify('exchange', 'CaXRifle', 'log_k', -1.0)

        assert run.exchange is not template.exchange
        assert run.minerals is template.minerals, 'untouched sections stay shared'


class TestValueShape:
    """The shape follows the parameter, not the number of temperature points."""

    def test_a_vector_parameter_is_a_list_even_with_one_point(self, three_point_db, tmp_path):
        single = tmp_path / 'one.dbs'
        single.write_text(THREE_POINT_DATABASE.replace(
            "'temperature points' 3   0.  25.  60.", "'temperature points' 1   25.")
            .replace('14.9398   13.9951   13.0272', '13.9951')
            .replace('-7.6765   -7.8136   -8.0527', '-7.8136')
            .replace('2.2257    1.8487    1.3330', '1.8487')
            .replace("'Debye-Huckel adh'   0.4939  0.5114 0.5465", "'Debye-Huckel adh'   0.5114")
            .replace("'Debye-Huckel bdh'   0.3253  0.3288 0.3346", "'Debye-Huckel bdh'   0.3288")
            .replace("'Debye-Huckel bdt'   0.0374  0.0410 0.0440", "'Debye-Huckel bdt'   0.0410"),
            newline='')
        database = Database(str(single))

        assert database.temp_points == 1
        assert database.value('minerals', 'Calcite', 'log_k') == pytest.approx([1.8487])

    def test_a_scalar_parameter_is_a_number(self, three_point_db):
        assert three_point_db.value('minerals', 'Calcite', 'weight') == pytest.approx(100.0872)

    def test_a_vector_parameter_is_a_list(self, three_point_db):
        assert len(three_point_db.value('minerals', 'Calcite', 'log_k')) == 3


class TestManualCoverage:
    """Every section CrunchTope recognises is parsed, and every documented field is editable.

    The section names are the Begin/End marker strings compiled into CrunchTope (grep for them in
    the source); the field lists are the ones the CrunchTope manual gives under each keyword
    block's 'Database Format' heading, except for the three the manual does not document as
    database rows at all, which come from read_exchange.F90 and database.F90 instead.
    """

    CRUNCHTOPE_SECTIONS = {
        'primary', 'secondary', 'gases', 'minerals', 'surface complexation',
        'aqueous kinetics', 'mineral kinetics', 'exchange', 'surface complexation parameters',
    }

    # As the manual writes them, under 'Database Format' for each keyword block.
    DOCUMENTED_FIELDS = {
        'primary_species': ['dh_size', 'charge', 'weight'],
        'secondary_species': ['log_k', 'dh_size', 'charge', 'weight'],
        'gases': ['molar_volume', 'log_k', 'weight'],
        'minerals': ['molar_volume', 'log_k', 'weight'],
        # Not in the manual as database rows; read out of the Fortran.
        'exchange': ['log_k', 'bfit'],
        'surface_complexation': ['log_k'],
        'surface_complexation_parameters': ['charge'],
    }

    def test_every_section_crunchtope_reads_is_parsed(self):
        from omphalos.database import SECTION_ATTRIBUTES

        assert set(SECTION_ATTRIBUTES) == self.CRUNCHTOPE_SECTIONS

    def test_the_shipped_databases_carry_no_unknown_section(self, db):
        assert set(db.sections) <= self.CRUNCHTOPE_SECTIONS

    @pytest.mark.parametrize('section,fields', sorted(DOCUMENTED_FIELDS.items()))
    def test_every_documented_field_is_editable(self, db, section, fields):
        entry = next(iter(getattr(db, section).values()))

        assert set(fields) <= set(entry.parameters)

    def test_the_mineral_kinetics_lines_the_manual_names_are_editable(self, db):
        # 'label', 'type', 'rate(25C)' and 'activation' are the five-line common format every
        # solid-liquid kinetic entry shares, per the manual.
        assert {'label', 'type', 'rate(25C)', 'activation'} <= set(
            db.mineral_kinetics['Calcite&default'].parameters
        )

    def test_the_manuals_rate_law_types_are_all_known(self, db):
        from omphalos.database import Mineral

        assert Mineral.rate_laws == frozenset({
            'tst', 'monod', 'irreversible', 'PrecipitationOnly', 'DissolutionOnly', 'MonodBiomass'
        })

    def test_the_deprecated_aqueous_kinetics_block_is_not_editable(self, db):
        # It belongs in the separate namelist file, which namelist.py handles. Recognising it here
        # only stops the following section from absorbing it.
        assert all(not entry.parameters for entry in db.aqueous_kinetics.values())

    def test_reaction_stoichiometry_is_deliberately_not_editable(self, db):
        # Changing a coefficient changes the reaction, and its log K would no longer be that
        # reaction's. Sweeping thermodynamics means sweeping log K.
        parameters = set(db.minerals['Calcite'].parameters)

        assert not parameters & {'reaction', 'reaction_species_count', 'name'}
