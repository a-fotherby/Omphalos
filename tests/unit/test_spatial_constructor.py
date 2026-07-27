"""Unit tests for core/spatial_constructor.py."""

import io
import contextlib
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

        assert array.shape == (int(float(xzones[0])), len(names))

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
