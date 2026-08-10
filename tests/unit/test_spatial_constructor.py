"""Unit tests for core/spatial_constructor.py."""

import io
import contextlib
import copy
import os

import numpy as np
import pytest
import yaml

from core import spatial_constructor as sc


def _template(directory, config_name):
    """Build a Template from a config in one of the test data directories."""
    from omphalos.template import Template

    original_dir = os.getcwd()
    os.chdir(directory)
    try:
        with open(config_name) as f:
            config = yaml.safe_load(f)
        with contextlib.redirect_stdout(io.StringIO()):
            return Template(config)
    finally:
        os.chdir(original_dir)


@pytest.fixture
def pump_first_template(rhea_test_dir):
    """A template whose first condition block is a pump condition with no region.

    column.in declares CONDITION pump before CONDITION upper_laterite, the initial condition applied
    over cells 1-100. Any code that only looks at the first condition block sees nothing to place.
    """
    return _template(rhea_test_dir, 'iron_rates.yaml')


@pytest.fixture
def initial_first_template(omphalos_test_dir):
    """A template whose first condition block is the domain-filling initial condition."""
    return _template(omphalos_test_dir, 'sukinda_cr.yaml')


def _drop_ph(block):
    """Remove pH from a condition block, as a condition constraining H+ directly would have.

    Sorting is lazy: ConditionBlock.parameters stays empty until check_condition_sort runs, which
    re-derives it from the raw contents whenever it finds it empty. So the entry has to go from both
    dictionaries, and the block has to have been sorted first for the parameters edit to survive.
    """
    block.parameters.pop('pH', None)
    block.contents.pop('pH', None)


def _sorted_blocks(template):
    """Return the condition blocks, sorted into species types as condition_variables would."""
    for condition in template.condition_blocks:
        template.check_condition_sort(condition)

    return template.condition_blocks


class TestConditionVariables:
    """Tests for the variable ordering shared by populate_array and its callers."""

    def test_concentrations_precede_minerals(self, initial_first_template):
        """Test that names are grouped, concentrations first, as callers assume."""
        names = sc.condition_variables(initial_first_template, primary_species=True, mineral_vols=True)
        block = initial_first_template.condition_blocks['initial']

        first_mineral = min(names.index(m) for m in block.mineral_volumes)
        last_species = max(names.index(s) for s in block.concentrations)
        assert last_species < first_mineral

    def test_names_are_unique(self, pump_first_template):
        """Test that a name declared by several conditions appears once."""
        names = sc.condition_variables(pump_first_template, primary_species=True, mineral_vols=True)
        assert len(names) == len(set(names))

    def test_union_across_conditions(self, pump_first_template):
        """Test that every condition's species are represented, not just the first block's."""
        names = sc.condition_variables(pump_first_template, primary_species=True, mineral_vols=False)
        for condition in pump_first_template.condition_blocks.values():
            for species in condition.concentrations:
                assert species in names

    def test_selection_flags(self, initial_first_template):
        """Test that the flags select which groups contribute."""
        concs = sc.condition_variables(initial_first_template, primary_species=True, mineral_vols=False)
        mins = sc.condition_variables(initial_first_template, primary_species=False, mineral_vols=True)
        both = sc.condition_variables(initial_first_template, primary_species=True, mineral_vols=True)

        assert both == concs + mins
        assert sc.condition_variables(initial_first_template, False, False) == []

    def test_ph_is_off_by_default(self, initial_first_template):
        """Test that pH is only reported when asked for."""
        assert 'pH' not in sc.condition_variables(initial_first_template, True, True)

    def test_ph_is_appended_last(self, initial_first_template):
        """Test that enabling pH adds a column without disturbing the existing ones.

        pH must come last so that a caller turning it on does not shift the species columns.
        """
        without = sc.condition_variables(initial_first_template, True, True, ph=False)
        with_ph = sc.condition_variables(initial_first_template, True, True, ph=True)

        assert with_ph == without + ['pH']

    def test_ph_alone(self, initial_first_template):
        """Test that pH can be requested without species or minerals."""
        assert sc.condition_variables(initial_first_template, False, False, ph=True) == ['pH']

    def test_ph_absent_from_conditions_gives_no_column(self, initial_first_template):
        """Test that a template declaring no pH contributes no pH column, as for any other name."""
        for block in _sorted_blocks(initial_first_template).values():
            _drop_ph(block)

        assert sc.condition_variables(initial_first_template, False, False, ph=True) == []

    def test_ph_keyword_is_case_insensitive(self, initial_first_template):
        """Test that the input file's spelling of the keyword does not matter.

        The parser keys condition entries on the verbatim leftmost word, so 'PH' and 'ph' reach the
        parameters dict unchanged and must still be recognised.
        """
        renamed = 0
        for block in _sorted_blocks(initial_first_template).values():
            if 'pH' in block.parameters:
                block.parameters['PH'] = block.parameters.pop('pH')
                renamed += 1

        assert renamed, 'template declares no pH, so the test would pass vacuously'
        assert sc.condition_variables(initial_first_template, False, False, ph=True) == ['pH']


class TestPopulateArray:
    """Tests for building the spatial initial condition array."""

    def test_condition_after_the_first_is_applied(self, pump_first_template):
        """Test that a template whose first condition has no region is still populated.

        Regression test: populate_array used to return inside the loop over condition blocks, so this
        template produced an all-zero array and the real initial condition was never read.
        """
        with contextlib.redirect_stdout(io.StringIO()):
            array = sc.populate_array(pump_first_template, primary_species=True, mineral_vols=False)

        assert not (array == 0).all(), 'initial condition was not applied'
        assert (array != 0).any(axis=1).all(), 'some grid cells were left unpopulated'

    def test_values_match_the_input_file(self, pump_first_template):
        """Test that the values placed are the ones the condition block declares."""
        names = sc.condition_variables(pump_first_template, primary_species=True, mineral_vols=False)
        with contextlib.redirect_stdout(io.StringIO()):
            array = sc.populate_array(pump_first_template, primary_species=True, mineral_vols=False)

        concentrations = pump_first_template.condition_blocks['upper_laterite'].concentrations
        for species in ('Ca++', 'Cl-', 'NO3-'):
            expected = float(concentrations[species][0])
            assert array[0, names.index(species)] == pytest.approx(expected)
            # The condition covers the whole column, so every row carries the same value.
            assert np.allclose(array[:, names.index(species)], expected)

    def test_non_numeric_constraints_become_nan(self, pump_first_template):
        """Test that entries like 'charge' or an equilibrating mineral are not forced to a number."""
        names = sc.condition_variables(pump_first_template, primary_species=True, mineral_vols=False)
        with contextlib.redirect_stdout(io.StringIO()):
            array = sc.populate_array(pump_first_template, primary_species=True, mineral_vols=False)

        # upper_laterite constrains 'Fe+++ Mn_Goethite' and 'SiO2(aq) Talc' by mineral equilibrium,
        # and 'O2(aq) O2(g) 0.00' by a gas partial pressure. None is a number.
        for species in ('Fe+++', 'SiO2(aq)', 'O2(aq)'):
            assert np.isnan(array[0, names.index(species)]), f'{species} should not be forced to a number'

    def test_shape_follows_discretization_and_variables(self, pump_first_template):
        """Test that the array is (grid cells x variables)."""
        names = sc.condition_variables(pump_first_template, primary_species=True, mineral_vols=True)
        xzones = pump_first_template.keyword_blocks['DISCRETIZATION'].contents['xzones']
        with contextlib.redirect_stdout(io.StringIO()):
            array = sc.populate_array(pump_first_template, primary_species=True, mineral_vols=True)

        # Summed over the zones rather than read off the leading token, so that this pins the
        # graded-grid behaviour and not just the uniform case the fixture happens to use.
        assert array.shape == (sc.zone_cell_count(xzones), len(names))

    def test_uncovered_cells_are_reported(self, pump_first_template, capsys):
        """Test that grid cells no condition covers are left at zero and warned about."""
        # Shrink the applied region so half the column is uncovered.
        pump_first_template.condition_blocks['upper_laterite'].region = [[[1, 50], [1, 1], [1, 1]]]

        array = sc.populate_array(pump_first_template, primary_species=True, mineral_vols=False)
        out = capsys.readouterr().out

        assert 'not covered by any condition region' in out
        assert (array[50:] == 0).all()
        assert (array[:50] != 0).any()

    def test_unused_condition_alone_gives_no_rows(self, initial_first_template):
        """Test that a condition never applied as an initial condition contributes nothing."""
        assert sc.compute_rows(initial_first_template, 'boundary') == []


class TestPh:
    """Tests for reading pH out of the condition block parameters."""

    def test_ph_value_is_placed_over_the_region(self, pump_first_template):
        """Test that the pH a condition declares is written to the cells it covers."""
        names = sc.condition_variables(pump_first_template, primary_species=False, mineral_vols=False, ph=True)
        with contextlib.redirect_stdout(io.StringIO()):
            array = sc.populate_array(pump_first_template, primary_species=False, mineral_vols=False, ph=True)

        expected = float(pump_first_template.condition_blocks['upper_laterite'].parameters['pH'][0])
        assert np.allclose(array[:, names.index('pH')], expected)

    def test_ph_is_not_converted_to_a_concentration(self, pump_first_template):
        """Test that the value recorded is pH itself, not 10**-pH.

        pH is -log10 of the H+ activity, so a concentration cannot be recovered without the activity
        coefficients from the speciation solve. The value is passed through unchanged instead.
        """
        names = sc.condition_variables(pump_first_template, primary_species=False, mineral_vols=False, ph=True)
        with contextlib.redirect_stdout(io.StringIO()):
            array = sc.populate_array(pump_first_template, primary_species=False, mineral_vols=False, ph=True)

        assert array[0, names.index('pH')] > 1, 'value looks like a concentration, not a pH'

    def test_ph_does_not_disturb_the_species_columns(self, pump_first_template):
        """Test that the species columns hold the same data whether or not pH is requested."""
        names = sc.condition_variables(pump_first_template, primary_species=True, mineral_vols=True)
        with contextlib.redirect_stdout(io.StringIO()):
            without = sc.populate_array(pump_first_template, primary_species=True, mineral_vols=True)
            with_ph = sc.populate_array(pump_first_template, primary_species=True, mineral_vols=True, ph=True)

        assert with_ph.shape[1] == without.shape[1] + 1
        np.testing.assert_array_equal(with_ph[:, :len(names)], without)

    def test_non_numeric_ph_becomes_nan(self, pump_first_template):
        """Test that a charge-balanced pH is not forced to a number.

        column.in constrains the pump condition with 'pH charge', which is a constraint rather than
        a value; the same is legal for the condition applied as the initial state.
        """
        pump_first_template.condition_blocks['upper_laterite'].parameters['pH'] = ['charge']

        names = sc.condition_variables(pump_first_template, primary_species=False, mineral_vols=False, ph=True)
        with contextlib.redirect_stdout(io.StringIO()):
            array = sc.populate_array(pump_first_template, primary_species=False, mineral_vols=False, ph=True)

        assert np.isnan(array[:, names.index('pH')]).all()

    def test_condition_without_ph_gets_nan(self, pump_first_template):
        """Test that a condition constraining H+ directly, rather than by pH, is not invented a value.

        The pH column exists because another condition declares one, so the cells belonging to this
        condition must read nan rather than silently inheriting a neighbour's pH.
        """
        blocks = _sorted_blocks(pump_first_template)
        # Split the column: the second half gets a condition that declares no pH at all.
        blocks['upper_laterite'].region = [[[1, 50], [1, 1], [1, 1]]]
        no_ph = copy.deepcopy(blocks['upper_laterite'])
        _drop_ph(no_ph)
        no_ph.region = [[[51, 100], [1, 1], [1, 1]]]
        blocks['no_ph'] = no_ph

        names = sc.condition_variables(pump_first_template, primary_species=False, mineral_vols=False, ph=True)
        with contextlib.redirect_stdout(io.StringIO()):
            array = sc.populate_array(pump_first_template, primary_species=False, mineral_vols=False, ph=True)

        column = array[:, names.index('pH')]
        assert not np.isnan(column[:50]).any()
        assert np.isnan(column[50:]).all()


class TestGridSize:
    """Tests for counting grid cells out of a CrunchTope zones specification.

    A zones keyword is a sequence of (cell count, cell size) pairs. Reading only the leading count
    under-counts every graded grid, which produces a short array rather than an obviously wrong one:
    populate_array then either raises IndexError on a condition region that runs past the end, or
    reports the missing tail as uncovered.
    """

    def test_uniform_grid(self):
        assert sc.zone_cell_count(['100', '10.0']) == 100

    def test_graded_grid_sums_the_counts(self):
        assert sc.zone_cell_count(['100', '0.2', '20', '0.5', '60', '1.0']) == 180

    def test_count_without_a_size(self):
        """CrunchTope accepts a bare count, so the pairing must not assume an even token count."""
        assert sc.zone_cell_count(['10']) == 10

    def test_counts_written_as_floats(self):
        assert sc.zone_cell_count(['100.0', '10.0']) == 100

    def test_array_covers_every_zone(self, pump_first_template):
        """A graded grid gets one row per cell, not one row per cell of its first zone."""
        disc = pump_first_template.keyword_blocks['DISCRETIZATION'].contents
        disc['xzones'] = ['100', '0.2', '20', '0.5', '60', '1.0']

        array = sc.initialise_array(pump_first_template, 3)

        assert array.shape == (180, 3)

    def test_axes_multiply(self, pump_first_template):
        disc = pump_first_template.keyword_blocks['DISCRETIZATION'].contents
        disc['xzones'] = ['3', '1.0', '2', '1.0']
        disc['yzones'] = ['4', '1.0']

        array = sc.initialise_array(pump_first_template, 2)

        assert array.shape == (20, 2)

    def test_unspecified_axes_default_to_one_cell(self, pump_first_template):
        """An axis with no zones keyword is one cell deep, and must not suppress the axes after it."""
        disc = pump_first_template.keyword_blocks['DISCRETIZATION'].contents
        disc['xzones'] = ['7', '1.0']
        disc.pop('yzones', None)
        disc['zzones'] = ['3', '1.0']

        array = sc.initialise_array(pump_first_template, 1)

        assert array.shape == (21, 1)
