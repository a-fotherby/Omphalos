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

    def test_search_file_condition_is_case_insensitive(self):
        """Test that any capitalisation of the CONDITION keyword is matched."""
        file_dict = {
            0: 'CONDITION initial',
            1: 'condition boundary',
            2: 'Condition other',
        }
        result = fm.search_file(file_dict, 'CONDITION')
        assert set(result) == {0, 1, 2}

    def test_search_file_condition_does_not_match_other_blocks(self):
        """Test that a CONDITION search does not pick up INITIAL/BOUNDARY_CONDITIONS blocks."""
        file_dict = {
            0: 'INITIAL_CONDITIONS',
            1: 'BOUNDARY_CONDITIONS',
            2: 'CONDITION initial',
        }
        result = fm.search_file(file_dict, 'CONDITION')
        assert set(result) == {2}

    def test_search_file_other_keywords_are_case_sensitive(self):
        """Test that non-CONDITION searches stay case sensitive.

        Condition-block entries such as 'temperature' share their name with keyword blocks, so
        matching case insensitively would mistake them for block delimiters.
        """
        file_dict = {
            0: 'TEMPERATURE',
            1: 'set_temperature 25.0',
            2: 'temperature 25.0',
        }
        result = fm.search_file(file_dict, 'TEMPERATURE')
        assert set(result) == {0}

    def test_search_file_ignores_unrelated_condition_lines(self):
        """Test that lower-case condition lines do not match unrelated keyword searches."""
        file_dict = {
            0: 'condition boundary',
            1: 'RUNTIME',
        }
        result = fm.search_file(file_dict, 'RUNTIME')
        assert set(result) == {1}

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

    def test_data_cats_keeps_category_names_intact(self, tmp_path):
        """Test that only the extension and output index are removed.

        The old implementation used rstrip with a character set, so 'rate.tec' became 'ra' and any
        category name ending in '.', 't', 'e' or 'c' was at risk.
        """
        for name in ('rate.tec', 'rate1.tec', 'saturation10.tec', 'toperatio_aq2.tec', 'volume.tec'):
            (tmp_path / name).touch()

        assert fm.data_cats(tmp_path) == {'rate', 'saturation', 'toperatio_aq', 'volume'}

    def test_data_cats_unaffected_by_directory_name(self, tmp_path):
        """Test that the containing directory's name cannot bleed into the category names."""
        run_dir = tmp_path / 'tec.rate1'
        run_dir.mkdir()
        (run_dir / 'totcon1.tec').touch()

        assert fm.data_cats(run_dir) == {'totcon'}


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


class TestOutputNaming:
    """Tests for naming the output files a run writes.

    A second sweep in the same directory must not overwrite the first, and the parameter record must
    end up named for the results it belongs to: one sweep's results beside another's parameters would
    join silently, both being indexed by run number.
    """

    def test_unique_path_is_the_plain_name_when_free(self, tmp_path):
        """Test that the first run gets the unadorned name."""
        assert fm.unique_output_path('results.nc', tmp_path) == tmp_path / 'results.nc'

    def test_unique_path_numbers_a_taken_name(self, tmp_path):
        """Test that successive runs number upwards rather than overwriting."""
        (tmp_path / 'results.nc').touch()
        assert fm.unique_output_path('results.nc', tmp_path) == tmp_path / 'results1.nc'

        (tmp_path / 'results1.nc').touch()
        (tmp_path / 'results2.nc').touch()
        assert fm.unique_output_path('results.nc', tmp_path) == tmp_path / 'results3.nc'

    def test_unique_path_works_for_any_name(self, tmp_path):
        """Test the helper is not specific to results.nc."""
        (tmp_path / 'conditions.nc').touch()
        assert fm.unique_output_path('conditions.nc', tmp_path) == tmp_path / 'conditions1.nc'

    def test_unique_path_ignores_directories(self, tmp_path):
        """Test that a directory of the same name does not count as taken."""
        (tmp_path / 'results.nc').mkdir()
        assert fm.unique_output_path('results.nc', tmp_path) == tmp_path / 'results.nc'

    @pytest.mark.parametrize('results,expected', [
        ('results.nc', 'conditions.nc'),
        ('results1.nc', 'conditions1.nc'),
        ('results12.nc', 'conditions12.nc'),
        ('/somewhere/else/results3.nc', 'conditions3.nc'),
        (None, 'conditions.nc'),
    ])
    def test_matching_name_carries_the_suffix_across(self, results, expected):
        """Test that the record is named for the results file it describes."""
        assert fm.matching_output_name(results) == expected

    def test_matching_name_accepts_another_base(self):
        """Test that the base name to derive from can be chosen."""
        assert fm.matching_output_name('results2.nc', 'inputs.nc') == 'inputs2.nc'


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

    def test_crunchtope_mode_returns_the_path_it_wrote(self, tmp_path, monkeypatch):
        """Test that the writer reports where the results went, and numbers a second call.

        Callers name the parameter record after this path, so that two sweeps in one directory cannot
        leave one sweep's results beside another's parameters.
        """
        import xarray as xr

        class MockInputFile:
            def __init__(self, file_num):
                self.file_num = file_num
                self.error_code = 0
                self.results = {'totcon': xr.Dataset(
                    {'species': (('X', 'Y', 'Z'), np.full((3, 1, 1), float(file_num)))},
                    coords={'X': [0.5, 1.5, 2.5], 'Y': [0.5], 'Z': [0.5]},
                )}

        monkeypatch.chdir(tmp_path)
        dataset = {0: MockInputFile(0)}

        first = fm.dataset_to_netcdf(dataset, simulator='crunchtope')
        assert first == Path('results.nc')

        dataset = {0: MockInputFile(0)}
        second = fm.dataset_to_netcdf(dataset, simulator='crunchtope')
        assert second == Path('results1.nc')
        assert fm.matching_output_name(second) == 'conditions1.nc'

    def test_crunchtope_mode_writes_the_union_of_categories(self, tmp_path, monkeypatch):
        """Test that a category the first run lacks is still written.

        Categories used to be read off the first run alone, so anything it happened not to produce was
        dropped for every run.
        """
        import netCDF4
        import xarray as xr

        def spatial(value):
            return xr.Dataset(
                {'species': (('X', 'Y', 'Z'), np.full((3, 1, 1), value))},
                coords={'X': [0.5, 1.5, 2.5], 'Y': [0.5], 'Z': [0.5]},
            )

        class MockInputFile:
            def __init__(self, file_num, categories):
                self.file_num = file_num
                self.error_code = 0
                self.results = {name: spatial(float(file_num)) for name in categories}

        # Run 0 produced no 'volume' output; run 1 did.
        dataset = {0: MockInputFile(0, ['totcon']), 1: MockInputFile(1, ['totcon', 'volume'])}

        monkeypatch.chdir(tmp_path)
        fm.dataset_to_netcdf(dataset, simulator='crunchtope')

        with netCDF4.Dataset(tmp_path / 'results.nc') as ds:
            groups = set(ds.groups)

        assert groups == {'totcon', 'volume'}


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


# The single-cell surface output of the Ex6B short-course exercise, verbatim in shape: nine names
# for eleven columns. The two unnamed ones are the free sites, and they come first.
SURFACE_TEC = ''' TITLE = "Surface Complex Concentration" 
VARIABLES = "X"   "Y"   "Z"   ">FeO-_str"   ">FeOH2+_str"   ">FeOHZn+_str"   ">FeO-_w"   ">FeOH2+_w"   ">FeOHZn+_w"    
 ZONE I=           1 , J=           1 , K=           1  F=POINT
   5.0E-01   5.0E-01   5.0E-01   2.2194E-03   8.8783E-02   3.9934E-05   2.8258E-03   3.4301E-07   1.5975E-03   1.1304E-01   1.4368E-08
'''


class TestUndeclaredColumns:
    """Tests for output that writes more columns than it names.

    CrunchTope's `surface` writer builds its VARIABLES line over the secondary surface complexes and
    then writes the data over the free sites *followed by* those complexes (GraphicsVisit.F90). The
    file therefore carries unnamed leading columns, and because they come first, reading the header at
    face value attributes every value to the wrong species.
    """

    def _write(self, tmp_path):
        path = tmp_path / 'surface1.tec'
        path.write_text(SURFACE_TEC)
        return path

    def test_the_data_width_is_counted_from_the_first_data_row(self, tmp_path):
        assert fm.data_width(self._write(tmp_path), skip=3) == 11

    def test_supplied_names_go_before_the_declared_ones(self):
        headers = ['X', 'Y', 'Z', 'a', 'b']
        reconciled = fm.reconcile_headers(headers, 7, leading_names=('site1', 'site2'))

        assert reconciled == ['X', 'Y', 'Z', 'site1', 'site2', 'a', 'b']

    def test_a_header_already_as_wide_as_the_data_is_untouched(self):
        headers = ['X', 'Y', 'Z', 'a']

        assert fm.reconcile_headers(headers, 4, leading_names=('unused',)) == headers

    def test_the_wrong_number_of_names_falls_back_to_placeholders(self):
        with pytest.warns(UserWarning, match='9 column names for 11'):
            reconciled = fm.reconcile_headers(['X', 'Y', 'Z'] + list('abcdef'), 11,
                                              leading_names=('only_one',))

        # Placeholders still put the declared names back on their own columns, which is the point:
        # a wrong name is worse than an obviously absent one.
        assert reconciled[3:5] == ['unnamed_1', 'unnamed_2']
        assert reconciled[5:] == list('abcdef')

    def test_the_sites_land_on_their_own_values(self, tmp_path):
        """Test that the reconstructed names describe the columns they are given.

        Checked against the deck rather than against the file: the weak site density is 40x the
        strong one, so the free-site columns must show that ratio. They do -- which is what
        establishes that the unnamed columns are the sites and that they come first.
        """
        self._write(tmp_path)

        ds = fm.parse_output(tmp_path, 'surface', 1,
                             leading_names=('>FeOH_strong', '>FeOH_weak'))

        strong = float(ds['>FeOH_strong'].values.ravel()[0])
        weak = float(ds['>FeOH_weak'].values.ravel()[0])
        assert strong == pytest.approx(2.2194e-03)
        assert weak / strong == pytest.approx(40.0, rel=1e-3)
        assert float(ds['>FeOHZn+_w'].values.ravel()[0]) == pytest.approx(1.4368e-08)

    def test_a_single_cell_file_parses(self, tmp_path):
        """Test that a 1x1x1 output is read, since every batch deck writes one."""
        self._write(tmp_path)

        ds = fm.parse_output(tmp_path, 'surface', 1,
                             leading_names=('>FeOH_strong', '>FeOH_weak'))

        assert dict(ds.sizes) == {'X': 1, 'Y': 1, 'Z': 1}


class TestNetcdfNames:
    """Tests for rewriting names netCDF will not accept.

    Two distinct rules, and only the first was handled before: '/' is forbidden anywhere, and the
    *first* character must be alphanumeric or an underscore. Every CrunchTope surface complex is
    named with a leading '>', so nothing from a SURFACE_COMPLEXATION deck could be written at all.
    """

    def test_a_slash_is_replaced_anywhere(self):
        assert fm.netcdf_name('C-Alk [eq/L]') == 'C-Alk [eq_per_L]'

    def test_a_leading_symbol_is_prefixed(self):
        assert fm.netcdf_name('>FeOHZn+_w') == '_>FeOHZn+_w'

    def test_symbols_after_the_first_character_are_left_alone(self):
        # netCDF accepts these, and renaming them would needlessly rewrite every species label.
        for name in ('Ca++', 'SO4--', 'CO2(aq)', 'X>FeO'):
            assert fm.netcdf_name(name) == name

    def test_a_name_starting_with_a_digit_is_left_alone(self):
        assert fm.netcdf_name('13CO2(aq)') == '13CO2(aq)'

    def test_a_dataset_is_renamed_in_place_of_its_variables(self):
        import xarray as xr

        ds = xr.Dataset({'>FeO-_str': ('X', [1.0]), 'Ca++': ('X', [2.0])})
        renamed = fm.sanitise_netcdf_names(ds)

        assert set(renamed.data_vars) == {'_>FeO-_str', 'Ca++'}

    def test_a_surface_complex_survives_a_netcdf_round_trip(self, tmp_path):
        """Test the thing that actually failed: writing the name to a file."""
        import xarray as xr

        ds = fm.sanitise_netcdf_names(xr.Dataset({'>FeOHZn+_w': ('X', [1.4368e-08])}))
        ds.to_netcdf(tmp_path / 'r.nc', group='surface', mode='a')

        assert '_>FeOHZn+_w' in xr.open_dataset(tmp_path / 'r.nc', group='surface').data_vars


TIME_SERIES_FILE = (
    '# Time series at grid cell:  80  13   1\n'
    'VARIABLES = "Time (hrs) " , "K+                 ", "Mg++               ", "Cl-  ", "\n'
    '  1.00000E-06                1.00000004749745E-09   2.00000004749745E-09   9.29560724540234E-10\n'
    '  2.00000E-06                1.10000004749745E-09   2.20000004749745E-09   9.39560724540234E-10\n'
    '  3.00000E-06                1.20000004749745E-09   2.40000004749745E-09   9.49560724540234E-10\n'
)


class TestTimeSeries:
    """Tests for reading CrunchTope's per-timestep output.

    This is the only output written every timestep rather than at chosen snapshot times, so it is the
    only way to see a transient the deck author did not think to ask for.
    """

    def _write(self, tmp_path, text=TIME_SERIES_FILE):
        path = tmp_path / 'Rolle.out'
        path.write_text(text)
        return path

    def test_a_truncated_header_quote_does_not_swallow_the_file(self, tmp_path):
        """Test that the file parses despite CrunchTope truncating its VARIABLES line mid-quote.

        The header ends on a lone opening quote. Left to its default quoting the C parser treats that
        as a string running to EOF and returns no rows at all -- silently, when names are supplied.
        """
        self._write(tmp_path)
        ds = fm.parse_time_series(tmp_path, 'Rolle.out')

        assert ds.sizes['step'] == 3
        assert list(ds.data_vars) == ['K+', 'Mg++', 'Cl-']

    def test_the_time_column_becomes_a_coordinate(self, tmp_path):
        """Test that time is a coordinate on a positional step dimension, not a dimension itself.

        Two runs of one sweep do not share a timestep sequence and need not even have the same number
        of steps, so concatenating on time values would interleave NaN at every unshared time.
        """
        self._write(tmp_path)
        ds = fm.parse_time_series(tmp_path, 'Rolle.out')

        assert ds['step'].values.tolist() == [0, 1, 2]
        assert 'time' in ds.coords
        assert 'time' not in ds.dims
        assert ds['time'].dims == ('step',)
        assert ds['time'].values[0] == pytest.approx(1.0e-06)
        assert ds['time'].attrs['long_name'] == 'Time (hrs)'

    def test_the_values_are_read(self, tmp_path):
        """Test that the data columns land against the right names."""
        self._write(tmp_path)
        ds = fm.parse_time_series(tmp_path, 'Rolle.out')

        assert ds['K+'].values[0] == pytest.approx(1.00000004749745e-09)
        assert ds['Mg++'].values[-1] == pytest.approx(2.40000004749745e-09)
        assert ds['Cl-'].values[1] == pytest.approx(9.39560724540234e-10)

    def test_a_malformed_exponent_is_repaired(self, tmp_path):
        """Test that a value written without its 'E' is read as the number, not as zero."""
        text = TIME_SERIES_FILE.replace('9.29560724540234E-10', '9.295607245-105')
        self._write(tmp_path, text)
        ds = fm.parse_time_series(tmp_path, 'Rolle.out')

        assert ds['Cl-'].values[0] == pytest.approx(9.295607245e-105)


class TestRepairExponents:
    """Tests for the repair of exponents CrunchTope writes without their 'E'.

    A value needing a three-digit exponent overruns its Fortran output field and loses the 'E',
    so '1.2345E-100' is written '1.2345-100'.
    """

    @pytest.mark.parametrize('written, meant', [
        ('1.2345-100', 1.2345e-100),
        ('-1.2345-100', -1.2345e-100),
        ('1.2345+100', 1.2345e100),
        ('9.999-305', 9.999e-305),
    ])
    def test_a_missing_exponent_marker_is_restored(self, written, meant):
        """Test that the repaired string parses as the number CrunchTope meant."""
        repaired = fm.repair_exponents(pd.Series([written]))
        assert float(repaired.iloc[0]) == pytest.approx(meant)

    @pytest.mark.parametrize('value', [
        '1.234e-05', '1.234E-100', '-1.234e+05', '0.5', '100', '1.0',
    ])
    def test_a_well_formed_value_is_untouched(self, value):
        """Test that a value that already has its exponent marker is left alone."""
        assert fm.repair_exponents(pd.Series([value])).iloc[0] == value

    def test_the_value_is_kept_rather_than_zeroed(self):
        """Test that the repair preserves the magnitude instead of substituting zero.

        Zeroing was the previous behaviour. The numerical difference is nil below 1e-100, but a
        column of repaired values no longer reads as a column of exact zeros.
        """
        repaired = fm.repair_exponents(pd.Series(['4.4408920985-016']))
        assert float(repaired.iloc[0]) > 0.0

    def test_an_unnamed_column_goes_at_the_end(self, tmp_path):
        """Test that a column the header does not name is placed last, not after the third one.

        Ex8's and Ex9's time series carry a trailing field the VARIABLES line never names, identically
        zero at every timestep. A time series has no X/Y/Z to insert behind -- its first column is the
        time -- so naming that column after the third, which is where spatial output wants one, would
        shift every name after it onto the wrong data.
        """
        text = (
            '# Time series at grid cell:   1   1   1\n'
            'VARIABLES = "Time (days)" , "HCO3-  ", "Ca++  ", "Ca44++  ", "pH  ", "\n'
            '  1.0E-10   1.50E-02   5.28E-03   1.14E-04   8.068E+00   0.00000000000000E+00\n'
            '  2.0E-10   1.51E-02   5.29E-03   1.15E-04   8.070E+00   0.00000000000000E+00\n'
        )
        (tmp_path / 'batch.out').write_text(text)
        ds = fm.parse_time_series(tmp_path, 'batch.out')

        assert list(ds.data_vars) == ['HCO3-', 'Ca++', 'Ca44++', 'pH', 'unnamed_1']
        # The named columns must still carry their own values.
        assert ds['HCO3-'].values[0] == pytest.approx(1.50e-02)
        assert ds['pH'].values[0] == pytest.approx(8.068)
        assert ds['unnamed_1'].values.tolist() == [0.0, 0.0]

    def test_more_names_than_columns_is_truncated(self, tmp_path):
        """Test that a header naming more columns than the file writes does not misalign the read."""
        text = (
            '# Time series at grid cell:   1   1   1\n'
            'VARIABLES = "Time (days)" , "A  ", "B  ", "C  "\n'
            '  1.0E-10   1.0   2.0\n'
            '  2.0E-10   1.1   2.1\n'
        )
        (tmp_path / 'short.out').write_text(text)
        ds = fm.parse_time_series(tmp_path, 'short.out')

        assert list(ds.data_vars) == ['A', 'B']
        assert ds['A'].values[1] == pytest.approx(1.1)
