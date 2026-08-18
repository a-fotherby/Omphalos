"""Unit tests for rhea/slurm_interface.py."""

import types
from unittest.mock import Mock

import numpy as np
import pytest
import xarray as xr

from rhea import slurm_interface as si


def _results(value=0.0, categories=('totcon',)):
    """Parsed output as a completed run carries it: one spatial Dataset per output category."""
    return {
        category: xr.Dataset(
            {'species': (('X', 'Y', 'Z'), np.full((3, 1, 1), float(value)))},
            coords={'X': [0.5, 1.5, 2.5], 'Y': [0.5], 'Z': [0.5]},
        )
        for category in categories
    }


def _input_file(error_code=0, categories=('totcon',)):
    """Build a stand-in for a completed InputFile carrying results."""
    return types.SimpleNamespace(error_code=error_code, results=_results(error_code, categories))


@pytest.fixture
def fake_runs(monkeypatch):
    """Patch unpickle/dataset_to_netcdf and let a test declare what each run returned.

    The test passes a dict of {run number: InputFile or None}, where None means the pickle could
    not be read (the run returned nothing at all). Returns the list of dicts handed to
    dataset_to_netcdf, so a test can assert what was compiled.
    """
    from core import file_methods as fm

    compiled = []

    def configure(runs):
        def unpickle(path):
            run = int(str(path).split('run')[1].split('/')[0])
            if runs.get(run) is None:
                raise FileNotFoundError(path)
            return runs[run]

        def record(dataset, simulator='crunchtope'):
            # Record the results objects themselves, keyed by run: compile_results deletes the
            # attribute from each InputFile once written, so inspecting them afterwards is too late.
            compiled.append({i: f.results for i, f in dataset.items()})

        monkeypatch.setattr(fm, 'unpickle', unpickle)
        monkeypatch.setattr(fm, 'dataset_to_netcdf', record)
        return compiled

    return configure


class TestCompileResults:
    """Tests for compile_results run accounting."""

    def test_all_runs_successful(self, fake_runs):
        """Test that clean runs are all compiled and reported."""
        compiled = fake_runs({i: _input_file() for i in range(3)})

        summary = si.compile_results(3)

        # 'results' is None here only because this fixture stubs out the netCDF writer.
        assert summary == {'total': 3, 'compiled': 3, 'no_output': [], 'errors': {}, 'results': None}
        assert sorted(compiled[0]) == [0, 1, 2]

    def test_error_codes_are_counted_and_excluded(self, fake_runs):
        """Test that runs returning a non-zero error code are not counted as compiled."""
        compiled = fake_runs({0: _input_file(), 1: _input_file(error_code=2), 2: _input_file(error_code=1)})

        summary = si.compile_results(3)

        assert summary['compiled'] == 1
        assert summary['errors'] == {1: 2, 2: 1}
        assert summary['no_output'] == []
        # Only the clean run should reach the netCDF writer.
        assert list(compiled[0]) == [0]

    def test_missing_pickles_are_counted_separately(self, fake_runs):
        """Test that runs which returned nothing are distinguished from runs that errored."""
        fake_runs({0: _input_file(), 1: None, 2: _input_file(error_code=3)})

        summary = si.compile_results(3)

        assert summary['compiled'] == 1
        assert summary['no_output'] == [1]
        assert summary['errors'] == {2: 3}

    def test_wholly_failed_sweep_writes_nothing(self, fake_runs, capsys):
        """Test that a sweep where every run failed reports zero compiled and writes no file."""
        compiled = fake_runs({0: _input_file(error_code=2), 1: None})

        summary = si.compile_results(2)

        assert summary['compiled'] == 0
        assert compiled == []          # dataset_to_netcdf never called
        assert 'no run returned usable output' in capsys.readouterr().out

    def test_reports_counts_to_stdout(self, fake_runs, capsys):
        """Test that the per-run breakdown is printed."""
        fake_runs({0: _input_file(), 1: _input_file(error_code=1), 2: None})

        si.compile_results(3)

        out = capsys.readouterr().out
        assert 'Files compiled: 1 of 3.' in out
        assert 'returned no output (1): [2]' in out
        assert 'failed during the run (1)' in out

    def test_input_files_without_error_code_are_compiled(self, fake_runs):
        """Test that an InputFile with no error_code attribute is treated as successful."""
        bare = Mock(spec=['results'])
        bare.results = _results()
        fake_runs({0: bare})

        summary = si.compile_results(1)

        assert summary['compiled'] == 1


class TestSpilling:
    """Tests for moving each run's results to disk as its pickle is read.

    results.nc is grouped by output category while the pickles are per run, so collating a sweep
    transposes the two. Spilling bounds that to one run plus one category, rather than holding every
    run's every category in memory at once.
    """

    def test_results_are_replaced_by_a_lazy_view(self, fake_runs):
        """Test that a compiled run's results are no longer held in memory."""
        from core.file_methods import SpilledResults

        compiled = fake_runs({0: _input_file(categories=('totcon', 'volume'))})
        si.compile_results(1)

        results = compiled[0][0]
        assert isinstance(results, SpilledResults)
        assert set(results) == {'totcon', 'volume'}

    def test_spilled_values_survive_the_round_trip(self, fake_runs, monkeypatch):
        """Test that what comes back through the spill file is what went in."""
        original = _results(value=7.0)['totcon']
        seen = {}

        def capture(dataset, simulator='crunchtope'):
            # Read a category back through the lazy view, as dataset_to_netcdf does.
            seen['totcon'] = dataset[0].results['totcon'].load()


        from core import file_methods as fm
        monkeypatch.setattr(fm, 'dataset_to_netcdf', capture)

        def unpickle(path):
            return types.SimpleNamespace(error_code=0, results={'totcon': original})

        monkeypatch.setattr(fm, 'unpickle', unpickle)
        si.compile_results(1)

        xr.testing.assert_allclose(seen['totcon'], original)

    def test_spill_directory_is_cleaned_up(self, fake_runs):
        """Test that the temporary spill files do not outlive the call."""
        compiled = fake_runs({0: _input_file()})
        si.compile_results(1)

        spill_path = compiled[0][0].path
        assert not spill_path.exists()
        assert not spill_path.parent.exists()

    def test_a_name_netcdf_forbids_is_rewritten_not_fatal(self, fake_runs, monkeypatch):
        """Test that a variable named with a '/' survives the spill.

        netCDF reads '/' as its group separator and refuses it in a variable name outright. Every
        MIN3P run carries one ('C-Alk [eq/L]'), and the spill is a netCDF file like any other, so it
        used to end the sweep here -- before dataset_to_netcdf, which does rename them, was reached.
        """
        from core import file_methods as fm

        seen = {}

        def capture(dataset, simulator='crunchtope'):
            seen['names'] = set(dataset[0].results['lbm'].load().data_vars)

        monkeypatch.setattr(fm, 'dataset_to_netcdf', capture)
        monkeypatch.setattr(fm, 'unpickle', lambda path: types.SimpleNamespace(
            error_code=0,
            results={'lbm': xr.Dataset({'C-Alk [eq/L]': ('time', np.array([1.0, 2.0]))})},
        ))

        si.compile_results(1, simulator='min3p')

        assert seen['names'] == {'C-Alk [eq_per_L]'}

    def test_results_without_categories_are_left_alone(self, fake_runs):
        """Test that a backend keeping a single Dataset in results is not spilled.

        PFLOTRAN stores one Dataset rather than a mapping of categories, so there is nothing to
        transpose and nothing to spill.
        """
        single = types.SimpleNamespace(error_code=0, results=_results()['totcon'])
        compiled = fake_runs({0: single})

        si.compile_results(1, simulator='pflotran')

        assert isinstance(compiled[0][0], xr.Dataset)


class TestResultsPathReporting:
    """Tests that compile_results says where it put the results.

    The parameter record written by rhea --compile-inputs is named after the results file, so the two
    stay paired when a sweep is re-run in the same directory.
    """

    def test_summary_carries_the_written_path(self, monkeypatch, tmp_path):
        """Test that whatever the writer reports comes back in the summary."""
        from core import file_methods as fm

        written = tmp_path / 'results1.nc'
        monkeypatch.setattr(fm, 'unpickle', lambda path: _input_file())
        monkeypatch.setattr(fm, 'dataset_to_netcdf', lambda dataset, simulator='crunchtope': written)

        summary = si.compile_results(1)

        assert summary['results'] == written

    def test_summary_reports_none_when_nothing_was_written(self, fake_runs):
        """Test that a wholly failed sweep reports no results file, so nothing is named after it."""
        fake_runs({0: _input_file(error_code=1)})

        summary = si.compile_results(1)

        assert summary['results'] is None


class TestClearRunDirectories:
    """A reused run directory used to keep everything the previous sweep left in it.

    prep_directories.sh does `mkdir run$N` and cleared nothing, so a rerun inherited the old
    database, deck, .tec output and .rst restart. CrunchTope writes output per snapshot, so a run
    producing fewer snapshots than last time left the surplus behind to be parsed as its own.
    """

    def _run_dir(self, tmp_path, number, *, files=('conc1.tec', 'conc2.tec', 'deck.in'),
                 pickle=True):
        directory = tmp_path / f'run{number}'
        directory.mkdir()
        for name in files:
            (directory / name).write_text('stale')
        if pickle:
            (directory / f'input_file{number}_complete.pkl').write_text('record')
        return directory

    def test_stale_output_is_removed(self, tmp_path):
        from rhea.slurm_interface import clear_run_directories

        directory = self._run_dir(tmp_path, 0)

        clear_run_directories(1, directory=tmp_path)

        assert not (directory / 'conc1.tec').exists()
        assert not (directory / 'deck.in').exists()

    def test_the_per_run_pickle_survives(self, tmp_path):
        # The record of what ran. A rerun must not destroy it before it has been compiled.
        from rhea.slurm_interface import clear_run_directories

        directory = self._run_dir(tmp_path, 0)

        clear_run_directories(1, directory=tmp_path)

        assert (directory / 'input_file0_complete.pkl').read_text() == 'record'

    def test_a_stage_aux_subdirectory_is_removed(self, tmp_path):
        from rhea.slurm_interface import clear_run_directories

        directory = self._run_dir(tmp_path, 0)
        aux = directory / 'stage0_aux'
        aux.mkdir()
        (aux / 'datacom.dbs').write_text('stale')

        clear_run_directories(1, directory=tmp_path)

        assert not aux.exists()

    def test_the_directory_itself_is_kept(self, tmp_path):
        # prep_directories.sh does `mkdir -p`, but the pickle has to stay somewhere.
        from rhea.slurm_interface import clear_run_directories

        directory = self._run_dir(tmp_path, 0)

        clear_run_directories(1, directory=tmp_path)

        assert directory.is_dir()

    def test_a_bigger_previous_sweep_is_refused(self, tmp_path):
        # run3..run7 from an eight-run sweep would not be rerun, and coeus would compile their
        # pickles beside this sweep's results, joined silently on run number.
        from rhea.slurm_interface import clear_run_directories

        for number in range(8):
            self._run_dir(tmp_path, number)

        with pytest.raises(SystemExit, match='left over from a larger sweep'):
            clear_run_directories(3, directory=tmp_path)

    def test_the_refusal_names_the_surplus(self, tmp_path):
        from rhea.slurm_interface import clear_run_directories

        for number in range(5):
            self._run_dir(tmp_path, number)

        with pytest.raises(SystemExit) as raised:
            clear_run_directories(3, directory=tmp_path)

        assert "'run3'" in str(raised.value) and "'run4'" in str(raised.value)
        assert "'run0'" not in str(raised.value)

    def test_nothing_is_touched_when_it_refuses(self, tmp_path):
        from rhea.slurm_interface import clear_run_directories

        for number in range(4):
            self._run_dir(tmp_path, number)

        with pytest.raises(SystemExit):
            clear_run_directories(2, directory=tmp_path)

        assert (tmp_path / 'run0' / 'conc1.tec').exists(), 'cleared before refusing'

    def test_a_first_run_has_nothing_to_do(self, tmp_path):
        from rhea.slurm_interface import clear_run_directories

        clear_run_directories(3, directory=tmp_path)

        assert list(tmp_path.iterdir()) == []

    def test_directories_that_only_look_like_runs_are_left_alone(self, tmp_path):
        # 'runtime_notes' starts with 'run' and is not a run directory.
        from rhea.slurm_interface import clear_run_directories

        other = tmp_path / 'runtime_notes'
        other.mkdir()
        (other / 'notes.md').write_text('keep me')

        clear_run_directories(1, directory=tmp_path)

        assert (other / 'notes.md').read_text() == 'keep me'

    def test_results_beside_the_run_directories_are_untouched(self, tmp_path):
        from rhea.slurm_interface import clear_run_directories

        self._run_dir(tmp_path, 0)
        (tmp_path / 'results.nc').write_text('previous results')
        (tmp_path / 'conditions.nc').write_text('previous record')

        clear_run_directories(1, directory=tmp_path)

        assert (tmp_path / 'results.nc').read_text() == 'previous results'
        assert (tmp_path / 'conditions.nc').read_text() == 'previous record'
