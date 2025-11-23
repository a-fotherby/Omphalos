"""Unit tests for core/file_methods.py."""

import pickle
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from core import file_methods as fm


class TestSearchFile:
    """Tests for the search_file function."""

    def test_search_file_basic(self):
        """Test basic search_file functionality."""
        file_dict = {
            0: 'TITLE',
            1: 'Test file',
            2: 'END',
            3: 'RUNTIME',
            4: 'time_units years',
            5: 'END',
        }
        result = fm.search_file(file_dict, 'RUNTIME')
        assert 3 in result

    def test_search_file_multiple_matches(self):
        """Test search_file with multiple matches."""
        file_dict = {
            0: 'END',
            1: 'content',
            2: 'END',
            3: 'more content',
            4: 'END',
        }
        result = fm.search_file(file_dict, 'END')
        assert len(result) == 3
        assert 0 in result
        assert 2 in result
        assert 4 in result

    def test_search_file_no_match(self):
        """Test search_file with no matches."""
        file_dict = {
            0: 'TITLE',
            1: 'Test file',
        }
        result = fm.search_file(file_dict, 'RUNTIME')
        assert len(result) == 0

    def test_search_file_case_sensitivity(self):
        """Test search_file respects case but allows 'condition'."""
        file_dict = {
            0: 'CONDITION initial',
            1: 'condition boundary',
            2: 'Condition other',  # This won't match
        }
        result = fm.search_file(file_dict, 'CONDITION')
        # Should match lines 0 and 1 (CONDITION and condition)
        assert 0 in result
        assert 1 in result

    def test_search_file_with_whitespace(self):
        """Test search_file with leading whitespace."""
        file_dict = {
            0: '  RUNTIME',
            1: '    END',
            2: 'TITLE',
        }
        result = fm.search_file(file_dict, 'RUNTIME', allow_white_space=True)
        assert 0 in result

    def test_search_file_without_whitespace(self):
        """Test search_file without allowing whitespace."""
        file_dict = {
            0: '  RUNTIME',
            1: 'RUNTIME',
        }
        result = fm.search_file(file_dict, 'RUNTIME', allow_white_space=False)
        assert 0 not in result
        assert 1 in result

    def test_search_file_returns_numpy_array(self):
        """Test that search_file returns a numpy array."""
        file_dict = {0: 'TEST'}
        result = fm.search_file(file_dict, 'TEST')
        assert isinstance(result, np.ndarray)

    def test_search_file_excludes_list_suffix(self):
        """Test that search_file excludes _LIST suffix matches."""
        file_dict = {
            0: 'CONDITION initial',
            1: 'CONDITION_LIST',
        }
        result = fm.search_file(file_dict, 'CONDITION')
        assert 0 in result
        assert 1 not in result  # CONDITION_LIST should not match


class TestDataCats:
    """Tests for the data_cats function."""

    def test_data_cats_basic(self, tmp_path):
        """Test basic data_cats functionality."""
        # Create mock .tec files
        (tmp_path / 'totcon1.tec').touch()
        (tmp_path / 'totcon2.tec').touch()
        (tmp_path / 'volume1.tec').touch()

        result = fm.data_cats(tmp_path)
        assert 'totcon' in result
        assert 'volume' in result

    def test_data_cats_empty_directory(self, tmp_path):
        """Test data_cats with empty directory."""
        result = fm.data_cats(tmp_path)
        assert len(result) == 0

    def test_data_cats_no_tec_files(self, tmp_path):
        """Test data_cats with no .tec files."""
        (tmp_path / 'file.txt').touch()
        (tmp_path / 'data.csv').touch()

        result = fm.data_cats(tmp_path)
        assert len(result) == 0

    def test_data_cats_returns_set(self, tmp_path):
        """Test that data_cats returns a set."""
        (tmp_path / 'test1.tec').touch()
        result = fm.data_cats(tmp_path)
        assert isinstance(result, set)


class TestPickleFunctions:
    """Tests for pickle_data_set and unpickle functions."""

    def test_pickle_and_unpickle_dict(self, tmp_path):
        """Test pickling and unpickling a dictionary."""
        data = {'key1': [1, 2, 3], 'key2': 'value'}

        fm.pickle_data_set(data, 'test.pkl', str(tmp_path))
        result = fm.unpickle(tmp_path / 'test.pkl')

        assert result == data

    def test_pickle_and_unpickle_nested(self, tmp_path):
        """Test pickling and unpickling nested structures."""
        data = {
            'outer': {
                'inner': [1, 2, 3],
                'deep': {'level': 3}
            }
        }

        fm.pickle_data_set(data, 'nested.pkl', str(tmp_path))
        result = fm.unpickle(tmp_path / 'nested.pkl')

        assert result == data

    def test_pickle_creates_directory(self, tmp_path):
        """Test that pickle_data_set creates directory if needed."""
        new_dir = tmp_path / 'new_subdir'
        data = {'test': 'data'}

        fm.pickle_data_set(data, 'test.pkl', str(new_dir))

        assert new_dir.exists()
        assert (new_dir / 'test.pkl').exists()

    def test_pickle_numpy_arrays(self, tmp_path):
        """Test pickling numpy arrays."""
        data = {'array': np.array([1, 2, 3, 4, 5])}

        fm.pickle_data_set(data, 'numpy.pkl', str(tmp_path))
        result = fm.unpickle(tmp_path / 'numpy.pkl')

        np.testing.assert_array_equal(result['array'], data['array'])

    def test_pickle_dataframe(self, tmp_path):
        """Test pickling pandas DataFrames."""
        data = {'df': pd.DataFrame({'A': [1, 2], 'B': [3, 4]})}

        fm.pickle_data_set(data, 'pandas.pkl', str(tmp_path))
        result = fm.unpickle(tmp_path / 'pandas.pkl')

        pd.testing.assert_frame_equal(result['df'], data['df'])

    def test_unpickle_nonexistent_file(self, tmp_path):
        """Test unpickling nonexistent file raises error."""
        with pytest.raises(FileNotFoundError):
            fm.unpickle(tmp_path / 'nonexistent.pkl')


class TestParseOutput:
    """Tests for the parse_output function."""

    def test_parse_output_basic(self, tmp_path):
        """Test basic TecPlot output parsing."""
        # Create a mock TecPlot file
        content = '''TITLE = "Test Output"
VARIABLES = "X" "Y" "Z" "Concentration"
ZONE T="zone1"
0.5 0.5 0.5 1.0
1.5 0.5 0.5 2.0
2.5 0.5 0.5 3.0
'''
        tec_file = tmp_path / 'test1.tec'
        tec_file.write_text(content)

        result = fm.parse_output(tmp_path, 'test', 1)

        assert 'Concentration' in result.data_vars
        assert len(result['X'].values) > 0

    def test_parse_output_multiple_variables(self, tmp_path):
        """Test parsing TecPlot with multiple variables."""
        content = '''TITLE = "Multi-variable Output"
VARIABLES = "X" "Y" "Z" "SO4--" "Fe++" "pH"
ZONE T="zone1"
0.5 0.5 0.5 1.0 1e-6 7.0
1.5 0.5 0.5 2.0 2e-6 6.5
'''
        tec_file = tmp_path / 'multi1.tec'
        tec_file.write_text(content)

        result = fm.parse_output(tmp_path, 'multi', 1)

        assert 'SO4--' in result.data_vars
        assert 'Fe++' in result.data_vars
        assert 'pH' in result.data_vars


class TestDatasetToNetcdf:
    """Tests for the dataset_to_netcdf function."""

    def test_dataset_to_netcdf_pflotran_mode(self):
        """Test dataset_to_netcdf in PFLOTRAN mode returns dataset."""
        import xarray as xr

        # Create mock dataset with results
        class MockInputFile:
            def __init__(self, file_num):
                self.file_num = file_num
                self.results = xr.Dataset({
                    'concentration': (['x'], [1.0, 2.0, 3.0])
                })

        dataset = {
            0: MockInputFile(0),
            1: MockInputFile(1),
        }

        result = fm.dataset_to_netcdf(dataset, simulator='pflotran')

        assert isinstance(result, xr.Dataset)
        assert 'concentration' in result.data_vars


class TestPathHandling:
    """Tests for path handling in file_methods."""

    def test_paths_accept_string(self, tmp_path):
        """Test that functions accept string paths."""
        data = {'test': 'data'}
        fm.pickle_data_set(data, 'test.pkl', str(tmp_path))
        assert (tmp_path / 'test.pkl').exists()

    def test_paths_accept_pathlib(self, tmp_path):
        """Test that unpickle accepts Path objects."""
        data = {'test': 'data'}
        fm.pickle_data_set(data, 'test.pkl', str(tmp_path))

        result = fm.unpickle(tmp_path / 'test.pkl')
        assert result == data
