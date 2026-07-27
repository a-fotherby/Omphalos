"""Unit tests for rhea/slurm_interface.py."""

from unittest.mock import Mock

import pytest

from rhea import slurm_interface as si


def _input_file(error_code=0):
    """Build a stand-in for a completed InputFile carrying results."""
    input_file = Mock()
    input_file.error_code = error_code
    input_file.results = {'totcon': Mock()}
    return input_file


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

        monkeypatch.setattr(fm, 'unpickle', unpickle)
        monkeypatch.setattr(fm, 'dataset_to_netcdf',
                            lambda dataset, simulator='crunchtope': compiled.append(dict(dataset)))
        return compiled

    return configure


class TestCompileResults:
    """Tests for compile_results run accounting."""

    def test_all_runs_successful(self, fake_runs):
        """Test that clean runs are all compiled and reported."""
        compiled = fake_runs({i: _input_file() for i in range(3)})

        summary = si.compile_results(3)

        assert summary == {'total': 3, 'compiled': 3, 'no_output': [], 'errors': {}}
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
        bare.results = {'totcon': Mock()}
        fake_runs({0: bare})

        summary = si.compile_results(1)

        assert summary['compiled'] == 1
