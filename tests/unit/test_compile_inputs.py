"""Unit tests for coeus/compile_inputs.py."""

import pickle
import types
from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from coeus.compile_inputs import compile_inputs, load_input_files, pairing_warning
from omphalos.database import Database


def _input_file(flow=1.0, condition_ph='7.0'):
    """A stand-in for a completed InputFile, indexed the way compile_inputs indexes one."""
    return types.SimpleNamespace(
        keyword_blocks={
            'FLOW': types.SimpleNamespace(contents={'constant_flow': [str(flow), 'default']}),
        },
        condition_blocks={
            'initial': types.SimpleNamespace(contents={'pH': [condition_ph]}),
        },
    )


def _write_runs(directory, values, missing=()):
    """Write one run directory per value, omitting the pickle for runs listed in missing."""
    for run_num, value in enumerate(values):
        run_dir = directory / f'run{run_num}'
        run_dir.mkdir()
        if run_num in missing:
            continue
        with open(run_dir / f'input_file{run_num}_complete.pkl', 'wb') as f:
            pickle.dump(_input_file(flow=value), f)


FLOW_CONFIG = {'number_of_files': 3, 'flow': {'constant_flow': ['custom', [1.0, 2.0, 4.0]]}}


class TestLoadInputFiles:
    """Tests for discovering and reading the per-run pickles."""

    def test_loads_every_run(self, tmp_path):
        """Test that each run directory's pickle is read, keyed by run number."""
        _write_runs(tmp_path, [1.0, 2.0, 4.0])

        input_files, missing = load_input_files(tmp_path, verbose=False)

        assert sorted(input_files) == [0, 1, 2]
        assert missing == []

    def test_missing_pickles_are_reported_not_fatal(self, tmp_path, capsys):
        """Test that a run which never wrote a pickle is skipped and named."""
        _write_runs(tmp_path, [1.0, 2.0, 4.0], missing=(1,))

        input_files, missing = load_input_files(tmp_path, verbose=False)

        assert sorted(input_files) == [0, 2]
        assert missing == [1]
        assert 'not found' in capsys.readouterr().out

    def test_no_run_directories_raises(self, tmp_path):
        """Test that a directory with no runs in it is an error, not an empty result."""
        with pytest.raises(FileNotFoundError, match='No run directories'):
            load_input_files(tmp_path, verbose=False)

    def test_run_directories_without_pickles_raises(self, tmp_path):
        """Test that run directories holding nothing readable is an error."""
        _write_runs(tmp_path, [1.0, 2.0], missing=(0, 1))

        with pytest.raises(FileNotFoundError, match='No input file pickles'):
            load_input_files(tmp_path, verbose=False)

    def test_runs_beyond_nine_are_ordered_numerically(self, tmp_path):
        """Test that run10 sorts after run9 rather than lexically."""
        _write_runs(tmp_path, [float(i) for i in range(12)])

        input_files, _ = load_input_files(tmp_path, verbose=False)

        assert sorted(input_files) == list(range(12))


class TestCompileInputs:
    """Tests for writing the parameter record."""

    def test_writes_a_group_per_block(self, tmp_path):
        """Test that a keyword block sweep is written, keyed by run number."""
        _write_runs(tmp_path, [1.0, 2.0, 4.0])

        summary = compile_inputs(FLOW_CONFIG, directory=tmp_path, verbose=False)

        assert summary['groups'] == 1
        assert summary['runs'] == [0, 1, 2]
        ds = xr.open_dataset(summary['output'], group='flow')
        assert list(ds['file_num'].values) == [0, 1, 2]
        assert np.allclose(ds['constant_flow'].values, [1.0, 2.0, 4.0])

    def test_condition_blocks_are_written_per_condition(self, tmp_path):
        """Test that a geochemical condition sweep lands in its own group."""
        _write_runs(tmp_path, [1.0, 2.0])
        config = {'number_of_files': 2, 'parameters': {'initial': {'pH': ['constant', 7.0]}}}

        summary = compile_inputs(config, directory=tmp_path, verbose=False)

        ds = xr.open_dataset(summary['output'], group='parameters/initial')
        assert np.allclose(ds['pH'].values, [7.0, 7.0])

    def test_values_come_from_the_runs_not_the_config(self, tmp_path):
        """Test that what is recorded is what ran.

        The point of the record: for random_uniform sweeps the config cannot say what was used, so the
        values are read back from the input files the workers actually wrote.
        """
        _write_runs(tmp_path, [3.5, 9.25, 11.0])
        config = {'number_of_files': 3, 'flow': {'constant_flow': ['random_uniform', [0.0, 100.0]]}}

        summary = compile_inputs(config, directory=tmp_path, verbose=False)

        ds = xr.open_dataset(summary['output'], group='flow')
        assert np.allclose(ds['constant_flow'].values, [3.5, 9.25, 11.0])

    def test_missing_runs_are_absent_from_the_record(self, tmp_path):
        """Test that a failed run is left out, and the surviving runs keep their own numbers."""
        _write_runs(tmp_path, [1.0, 2.0, 4.0], missing=(1,))

        summary = compile_inputs(FLOW_CONFIG, directory=tmp_path, verbose=False)

        assert summary['missing'] == [1]
        ds = xr.open_dataset(summary['output'], group='flow')
        assert list(ds['file_num'].values) == [0, 2]
        assert np.allclose(ds['constant_flow'].values, [1.0, 4.0])

    def test_config_varying_nothing_writes_no_file(self, tmp_path, capsys):
        """Test that a config with no swept parameters says so rather than writing an empty file."""
        _write_runs(tmp_path, [1.0])

        summary = compile_inputs({'number_of_files': 1}, directory=tmp_path, verbose=False)

        assert summary == {'output': None, 'groups': 0, 'runs': [0], 'missing': []}
        assert 'No varied parameters' in capsys.readouterr().out
        assert not (tmp_path / 'conditions.nc').exists()

    def test_existing_output_is_replaced(self, tmp_path):
        """Test that a rerun overwrites rather than appending to a stale record."""
        _write_runs(tmp_path, [1.0, 2.0, 4.0])
        (tmp_path / 'conditions.nc').write_text('not a netCDF file')

        summary = compile_inputs(FLOW_CONFIG, directory=tmp_path, verbose=False)

        ds = xr.open_dataset(summary['output'], group='flow')
        assert np.allclose(ds['constant_flow'].values, [1.0, 2.0, 4.0])

    def test_output_name_is_configurable(self, tmp_path):
        """Test the output filename can be chosen, as the CLI's -o does."""
        _write_runs(tmp_path, [1.0, 2.0, 4.0])

        summary = compile_inputs(FLOW_CONFIG, output='my_record.nc', directory=tmp_path, verbose=False)

        assert summary['output'] == tmp_path / 'my_record.nc'
        assert (tmp_path / 'my_record.nc').exists()

    def test_verbose_controls_the_per_file_chatter(self, tmp_path, capsys):
        """Test that verbose=False keeps the per-run lines out of a rhea run's output."""
        _write_runs(tmp_path, [1.0, 2.0, 4.0])

        compile_inputs(FLOW_CONFIG, directory=tmp_path, verbose=False)
        quiet = capsys.readouterr().out
        compile_inputs(FLOW_CONFIG, directory=tmp_path, verbose=True)
        loud = capsys.readouterr().out

        assert 'Loaded' not in quiet and 'Written group' not in quiet
        assert 'Loaded' in loud and 'Written group' in loud
        # The summary line is worth having either way.
        assert 'Conditions written to' in quiet and 'Conditions written to' in loud

    def test_unreadable_entry_becomes_nan(self, tmp_path, capsys):
        """Test that a parameter the input files do not carry is warned about, not fatal."""
        _write_runs(tmp_path, [1.0, 2.0, 4.0])
        config = {'number_of_files': 3, 'flow': {'constant_flow': ['custom', [1.0, 2.0, 4.0]],
                                                'nonexistent_entry': ['constant', 1.0]}}

        summary = compile_inputs(config, directory=tmp_path, verbose=False)

        ds = xr.open_dataset(summary['output'], group='flow')
        assert np.isnan(ds['nonexistent_entry'].values).all()
        assert 'Could not read' in capsys.readouterr().out


class TestPairingWarning:
    """Tests for the guard against writing a record that pairs with the wrong results file.

    A sweep re-run in the same directory writes results1.nc, and its record belongs in
    conditions1.nc. The standalone script cannot know which sweep it is being run for, so it says so
    rather than silently pairing with the first.
    """

    def test_silent_with_a_single_results_file(self, tmp_path):
        """Test that the ordinary case says nothing."""
        (tmp_path / 'results.nc').touch()
        assert pairing_warning(tmp_path) is None

    def test_silent_with_no_results_file(self, tmp_path):
        """Test that compiling before any results exist is not flagged."""
        assert pairing_warning(tmp_path) is None

    def test_warns_when_several_results_files_exist(self, tmp_path):
        """Test that an ambiguous directory is flagged, with the pairing spelled out."""
        for name in ('results.nc', 'results1.nc', 'results2.nc'):
            (tmp_path / name).touch()

        warning = pairing_warning(tmp_path)

        assert warning is not None
        assert '3 results files' in warning
        assert 'results1.nc -> conditions1.nc' in warning
        assert 'results2.nc -> conditions2.nc' in warning

    def test_silent_when_the_name_was_chosen_explicitly(self, tmp_path):
        """Test that passing -o means the caller has already decided; no need to warn."""
        for name in ('results.nc', 'results1.nc'):
            (tmp_path / name).touch()

        assert pairing_warning(tmp_path, output='conditions1.nc') is None


class TestDatabaseParameters:
    """The database a run used is part of the record, and cannot be re-derived from the config
    where the sweep is random_uniform."""

    DB_PATH = Path(__file__).parent.parent / 'omphalos_test' / 'SukindaCr53.dbs'

    def _write_runs(self, directory, log_ks):
        for run_num, log_k in enumerate(log_ks):
            database = Database(str(self.DB_PATH))
            database.modify('exchange', 'CaXRifle', 'log_k', log_k)
            database.modify('minerals', 'Calcite', 'log_k', log_k)
            run_dir = directory / f'run{run_num}'
            run_dir.mkdir()
            input_file = _input_file()
            input_file.database = database
            with open(run_dir / f'input_file{run_num}_complete.pkl', 'wb') as f:
                pickle.dump(input_file, f)

    CONFIG = {
        'number_of_files': 3,
        'database_parameters': {
            'exchange': {'CaXRifle': {'log_k': ['custom', [-1.2, -0.9, -0.6]]}},
            'minerals': {'Calcite': {'log_k': ['custom', [-1.2, -0.9, -0.6]]}},
        },
    }

    def test_scalar_parameter_is_recorded_per_run(self, tmp_path):
        self._write_runs(tmp_path, [-1.2, -0.9, -0.6])

        compile_inputs(self.CONFIG, directory=tmp_path, verbose=False)

        recorded = xr.open_dataset(tmp_path / 'conditions.nc',
                                   group='database_parameters/exchange/CaXRifle')
        assert recorded['log_k'].values == pytest.approx([-1.2, -0.9, -0.6])

    def test_a_log_k_vector_gains_a_temperature_dimension(self, tmp_path):
        self._write_runs(tmp_path, [-1.2, -0.9, -0.6])

        compile_inputs(self.CONFIG, directory=tmp_path, verbose=False)

        recorded = xr.open_dataset(tmp_path / 'conditions.nc',
                                   group='database_parameters/minerals/Calcite')
        assert recorded['log_k'].dims == ('file_num', 'temp_point')
        assert recorded['log_k'].shape == (3, 8)
        assert recorded['log_k'].values[0] == pytest.approx([-1.2] * 8)

    def test_values_come_from_the_runs_not_the_config(self, tmp_path):
        # What a run actually used is the point of the record; a random_uniform sweep cannot be
        # re-derived from the YAML at all.
        self._write_runs(tmp_path, [-2.0, -2.0, -2.0])

        compile_inputs(self.CONFIG, directory=tmp_path, verbose=False)

        recorded = xr.open_dataset(tmp_path / 'conditions.nc',
                                   group='database_parameters/exchange/CaXRifle')
        assert recorded['log_k'].values == pytest.approx([-2.0, -2.0, -2.0])

    def test_a_config_without_database_parameters_writes_no_such_group(self, tmp_path):
        _write_runs(tmp_path, [1.0, 2.0, 4.0])

        compile_inputs(FLOW_CONFIG, directory=tmp_path, verbose=False)

        with pytest.raises(OSError):
            xr.open_dataset(tmp_path / 'conditions.nc', group='database_parameters')


class TestDatabaseLogK:
    """The pressure a database was recomputed at is the one thing the database itself cannot say."""

    CONFIG = {
        'number_of_files': 3,
        'database_logk': {
            'reactions': ['Calcite'],
            'pressure': ['custom', [1.0, 250.0, 500.0]],
        },
    }

    def _write_runs(self, directory, settings):
        for run_num, used in enumerate(settings):
            run_dir = directory / f'run{run_num}'
            run_dir.mkdir()
            input_file = _input_file()
            input_file.logk_settings = used
            with open(run_dir / f'input_file{run_num}_complete.pkl', 'wb') as f:
                pickle.dump(input_file, f)

    def test_the_pressure_is_recorded_per_run(self, tmp_path):
        self._write_runs(tmp_path, [{'pressure': p} for p in (1.0, 250.0, 500.0)])

        compile_inputs(self.CONFIG, directory=tmp_path, verbose=False)

        recorded = xr.open_dataset(tmp_path / 'conditions.nc', group='database_logk')
        assert recorded['pressure'].values == pytest.approx([1.0, 250.0, 500.0])

    def test_values_come_from_the_runs_not_the_config(self, tmp_path):
        self._write_runs(tmp_path, [{'pressure': p} for p in (10.0, 20.0, 30.0)])

        compile_inputs(self.CONFIG, directory=tmp_path, verbose=False)

        recorded = xr.open_dataset(tmp_path / 'conditions.nc', group='database_logk')
        assert recorded['pressure'].values == pytest.approx([10.0, 20.0, 30.0])

    def test_a_run_recording_nothing_is_reported_not_invented(self, tmp_path):
        import numpy as np

        self._write_runs(tmp_path, [{'pressure': 1.0}, None, {'pressure': 500.0}])

        compile_inputs(self.CONFIG, directory=tmp_path, verbose=False)

        recorded = xr.open_dataset(tmp_path / 'conditions.nc', group='database_logk')
        assert np.isnan(recorded['pressure'].values[1])

    def test_a_fixed_pressure_writes_no_group(self, tmp_path):
        # Nothing varies between runs, so there is nothing per-run to record. Paired with a flow
        # sweep so the file is written either way and its absence means absence, not an empty run.
        _write_runs(tmp_path, [1.0, 2.0, 4.0])
        config = dict(FLOW_CONFIG, database_logk={'pressure': 500.0})

        compile_inputs(config, directory=tmp_path, verbose=False)

        assert xr.open_dataset(tmp_path / 'conditions.nc', group='flow') is not None
        with pytest.raises(OSError):
            xr.open_dataset(tmp_path / 'conditions.nc', group='database_logk')


class TestStagedDatabaseLogK:
    """A staged sweep has no per-stage record to read: one pickle survives per run.

    Reading it recorded that stage's value for every stage -- 500/500 where the sweep applied 200
    then 500. Re-derived from the config instead, as every other block does for a staged sweep.
    """

    CONFIG = {
        'number_of_files': 2,
        'restart_chain': {'stages': 2},
        'database_logk': {
            'reactions': ['Calcite'],
            'pressure': ['staged', [[200.0, 200.0], [500.0, 500.0]]],
        },
    }

    def _write_runs(self, directory):
        for run_num in range(2):
            run_dir = directory / f'run{run_num}'
            run_dir.mkdir()
            input_file = _input_file()
            # Whichever stage wrote last is what the pickle holds.
            input_file.logk_settings = {'pressure': 500.0}
            with open(run_dir / f'input_file{run_num}_complete.pkl', 'wb') as f:
                pickle.dump(input_file, f)

    def test_each_stage_gets_its_own_pressure(self, tmp_path):
        import numpy as np

        self._write_runs(tmp_path)

        compile_inputs(self.CONFIG, directory=tmp_path, verbose=False)

        recorded = xr.open_dataset(tmp_path / 'conditions.nc', group='database_logk')['pressure']
        assert recorded.dims == ('file_num', 'stage_num')
        assert np.allclose(recorded.values, [[200.0, 500.0], [200.0, 500.0]])


# ---------------------------------------------------------------------------
# The MIN3P backend. A MIN3P config names positional coordinates under
# 'modifications' rather than keyword blocks, so it is recorded as one group of
# that name with a variable per modification.
# ---------------------------------------------------------------------------
MIN3P_DAT = (
    "'global control parameters'\n"
    "'A batch problem'\n"
    ".false.                       ;varsat_flow\n"
    "'done'\n"
    "\n"
    "'initial condition - local geochemistry'\n"
    "'number and name of zone'\n"
    "1\n"
    "'zone one'\n"
    "'mineral input'\n"
    "1.00d-2   .true. 'geometric'  ;phim, minequil, update_type\n"
    "'guess for ph'\n"
    "7.0\n"
    "'done'\n"
).replace('\n', '\r\n')

MIN3P_CONFIG = {
    'number_of_files': 3,
    'modifications': {
        'calcite_volume': {'alias': 'calcite_volume', 'method': 'linspace',
                           'params': [0.005, 0.02]},
    },
}


def _write_min3p_runs(directory, volumes, update_types=None):
    """Write one run directory per volume, each holding the deck that run used.

    Built through min3p's own Template and block.modify rather than by string substitution, so what
    is pickled is the object a worker would have pickled.
    """
    from min3p.template import Template

    for run_num, volume in enumerate(volumes):
        run_dir = directory / f'run{run_num}'
        run_dir.mkdir()
        deck = run_dir / 'batch.dat'
        deck.write_text(MIN3P_DAT, newline='')

        input_file = Template({'template': str(deck), 'number_of_files': 1})
        block = input_file.keyword_blocks['initial condition - local geochemistry']
        block.modify('mineral input', volume, token_pos=0, line_index=0)

        if update_types is not None:
            block.modify('mineral input', update_types[run_num], token_pos=2, line_index=0)

        with open(run_dir / f'input_file{run_num}_complete.pkl', 'wb') as f:
            pickle.dump(input_file, f)


class TestMin3pModifications:
    """Tests for recording a MIN3P sweep."""

    def test_modifications_are_written_as_one_group(self, tmp_path):
        """Test that every modification the config names becomes a variable of one group."""
        _write_min3p_runs(tmp_path, ['0.005', '0.0125', '0.02'])

        summary = compile_inputs(MIN3P_CONFIG, directory=tmp_path, verbose=False,
                                 simulator='min3p')

        assert summary['groups'] == 1
        ds = xr.open_dataset(summary['output'], group='modifications')
        assert list(ds['file_num'].values) == [0, 1, 2]
        assert np.allclose(ds['calcite_volume'].values, [0.005, 0.0125, 0.02])

    def test_values_come_from_the_runs_not_the_config(self, tmp_path):
        """Test that what is recorded is the token in the deck, not what the config asked for."""
        _write_min3p_runs(tmp_path, ['0.003', '0.011', '0.019'])

        summary = compile_inputs(MIN3P_CONFIG, directory=tmp_path, verbose=False,
                                 simulator='min3p')

        ds = xr.open_dataset(summary['output'], group='modifications')
        assert np.allclose(ds['calcite_volume'].values, [0.003, 0.011, 0.019])

    def test_a_fortran_exponent_is_read_as_a_number(self, tmp_path):
        """Test that a token MIN3P writes as '1.00d-2' is recorded as 0.01, not skipped."""
        _write_min3p_runs(tmp_path, ['1.00d-2', '2.50D-2', '4e-2'])

        summary = compile_inputs(MIN3P_CONFIG, directory=tmp_path, verbose=False,
                                 simulator='min3p')

        ds = xr.open_dataset(summary['output'], group='modifications')
        assert np.allclose(ds['calcite_volume'].values, [0.01, 0.025, 0.04])

    def test_a_string_valued_modification_is_recorded_as_text(self, tmp_path):
        """Test that an enumerated value is kept, rather than becoming a column of NaNs."""
        _write_min3p_runs(tmp_path, ['0.005'] * 3,
                          update_types=["'geometric'", "'surface'", "'geometric'"])
        config = dict(MIN3P_CONFIG)
        config['modifications'] = dict(
            config['modifications'],
            update_type={'block': 'initial condition - local geochemistry',
                         'keyword': 'mineral input', 'line': 0, 'token': 2,
                         'method': 'custom', 'params': ["'geometric'", "'surface'", "'geometric'"]},
        )

        summary = compile_inputs(config, directory=tmp_path, verbose=False, simulator='min3p')

        ds = xr.open_dataset(summary['output'], group='modifications')
        assert list(ds['update_type'].values) == ['geometric', 'surface', 'geometric']

    def test_an_unreadable_coordinate_is_reported_not_invented(self, tmp_path, capsys):
        """Test that a coordinate no longer in the deck becomes NaN and says so."""
        _write_min3p_runs(tmp_path, ['0.005', '0.0125', '0.02'])
        config = dict(MIN3P_CONFIG)
        config['modifications'] = {
            'phantom': {'block': 'initial condition - local geochemistry',
                        'keyword': 'mineral input', 'line': 7, 'token': 0,
                        'method': 'constant', 'params': 1.0},
        }

        summary = compile_inputs(config, directory=tmp_path, verbose=False, simulator='min3p')

        assert 'Could not read modifications/phantom' in capsys.readouterr().out
        ds = xr.open_dataset(summary['output'], group='modifications')
        assert np.isnan(ds['phantom'].values).all()

    def test_a_config_varying_nothing_writes_no_file(self, tmp_path):
        """Test that a MIN3P config with no modifications is reported, not written empty."""
        _write_min3p_runs(tmp_path, ['0.005', '0.0125', '0.02'])

        summary = compile_inputs({'number_of_files': 3}, directory=tmp_path, verbose=False,
                                 simulator='min3p')

        assert summary == {'output': None, 'groups': 0, 'runs': [0, 1, 2], 'missing': []}

    def test_a_staged_chain_carries_a_stage_dimension(self, tmp_path):
        """Test that a chain's record aligns with a staged results file.

        MIN3P applies the same modifications to every stage and varies only the final solution time,
        so the values repeat across stages rather than being re-derived per stage as CrunchTope's are.
        """
        _write_min3p_runs(tmp_path, ['0.005', '0.0125', '0.02'])
        config = dict(MIN3P_CONFIG,
                      restart_chain={'stages': 2, 'final_times': [6.0, 12.0]})

        summary = compile_inputs(config, directory=tmp_path, verbose=False, simulator='min3p')

        recorded = xr.open_dataset(summary['output'], group='modifications')['calcite_volume']
        assert recorded.dims == ('file_num', 'stage_num')
        assert np.allclose(recorded.values, [[0.005] * 2, [0.0125] * 2, [0.02] * 2])

    def test_a_min3p_config_read_as_crunchtope_says_which_flag_to_pass(self, tmp_path, capsys):
        """Test that the one config shape that records nothing points at the reason."""
        _write_min3p_runs(tmp_path, ['0.005', '0.0125', '0.02'])

        summary = compile_inputs(MIN3P_CONFIG, directory=tmp_path, verbose=False)

        assert summary['groups'] == 0
        assert 'Pass -m' in capsys.readouterr().out

    def test_an_unknown_backend_is_refused(self, tmp_path):
        """Test that a backend with no reader is an error rather than an empty record."""
        _write_min3p_runs(tmp_path, ['0.005'])

        with pytest.raises(ValueError, match='pflotran'):
            compile_inputs(MIN3P_CONFIG, directory=tmp_path, verbose=False, simulator='pflotran')
