"""Unit tests for core/attributes.py."""

import contextlib
import copy
import io
import os

import numpy as np
import pytest
import xarray as xr
import yaml

from core import attributes as attr
from core import spatial_constructor as sc


@pytest.fixture
def sparse_dataset(omphalos_test_dir):
    """Two InputFiles keyed 0 and 5, as though runs 1-4 had failed and been filtered out.

    Positional indexing would label these 0 and 1, silently misaligning them with results.nc.
    """
    from omphalos.template import Template

    original_dir = os.getcwd()
    os.chdir(omphalos_test_dir)
    try:
        with open('sukinda_cr.yaml') as f:
            config = yaml.safe_load(f)
        with contextlib.redirect_stdout(io.StringIO()):
            template = Template(config)
    finally:
        os.chdir(original_dir)

    return {0: copy.deepcopy(template), 5: copy.deepcopy(template)}


def _with_results(dataset, category='totcon'):
    """Attach a minimal spatial output to each InputFile, as a completed run would carry."""
    for file_num, input_file in dataset.items():
        input_file.results = {
            category: xr.Dataset(
                {'dummy': (('X', 'Y', 'Z'), np.full((10, 1, 1), float(file_num)))},
                coords={'X': np.arange(10) + 0.5, 'Y': [0.5], 'Z': [0.5]},
            )
        }
    return dataset


class TestFileNumLabelling:
    """Tests that attribute tables are keyed by run number, not by position."""

    def test_get_condition_is_indexed_by_file_num(self, sparse_dataset):
        """Test that get_condition labels rows with the run numbers it was given."""
        with contextlib.redirect_stdout(io.StringIO()):
            df = attr.get_condition(sparse_dataset, 'initial', species_concs=True, mineral_volumes=True)

        assert list(df.index) == [0, 5]
        assert df.index.name == 'file_num'

    def test_boundary_condition_is_indexed_by_file_num(self, sparse_dataset):
        """Test that boundary_condition keeps its documented file-number index."""
        with contextlib.redirect_stdout(io.StringIO()):
            df = attr.boundary_condition(sparse_dataset, boundary='x_begin')

        assert list(df.index) == [0, 5]
        assert df.index.name == 'file_num'

    def test_mineral_and_aqueous_rates_are_indexed_by_file_num(self, sparse_dataset):
        """Test the rate tables carry the same index."""
        for table in (attr.mineral_rates(sparse_dataset), attr.aqueous_rates(sparse_dataset)):
            assert list(table.index) == [0, 5]
            assert table.index.name == 'file_num'

    def test_initial_conditions_labels_file_num(self, sparse_dataset):
        """Test that the spatial initial-condition Dataset carries the run numbers as a coordinate."""
        dataset = _with_results(sparse_dataset)
        with contextlib.redirect_stdout(io.StringIO()):
            ds = attr.initial_conditions(dataset, concentrations=True, minerals=False)

        assert 'file_num' in ds.coords
        assert list(ds['file_num'].values) == [0, 5]

    def test_initial_conditions_variables_match_the_array_columns(self, sparse_dataset):
        """Test that the variables are named from the same source that orders the array columns.

        These were derived independently, so any divergence in ordering labelled each species with
        another's data.
        """
        dataset = _with_results(sparse_dataset)
        expected = sc.condition_variables(dataset[0], primary_species=True, mineral_vols=False)
        with contextlib.redirect_stdout(io.StringIO()):
            ds = attr.initial_conditions(dataset, concentrations=True, minerals=False)

        assert [v for v in ds.data_vars] == expected

    def test_initial_conditions_values_come_from_the_condition_block(self, sparse_dataset):
        """Test that a known species carries its input file value across the domain."""
        dataset = _with_results(sparse_dataset)
        with contextlib.redirect_stdout(io.StringIO()):
            ds = attr.initial_conditions(dataset, concentrations=True, minerals=False)

        expected = float(dataset[0].condition_blocks['initial'].concentrations['Ca++'][0])
        assert np.allclose(ds['Ca++'].values, expected)
