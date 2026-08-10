"""Unit tests for omphalos/run.py."""

from unittest.mock import Mock

import pytest

# omphalos.run imports omphalos.settings, which install.sh creates from settings_default.py and
# which is not tracked, so skip these tests where it is absent.
run = pytest.importorskip(
    'omphalos.run',
    reason='requires omphalos/settings.py (created by install.sh)',
)


class TestCrunchTopeErrorPatterns:
    """Tests for the CrunchTope stdout error patterns."""

    def test_missing_input_file_is_an_error_pattern(self):
        """Test that CrunchTope losing the input file is treated as an error.

        CrunchTope truncates long input file paths and then waits on stdin, which would otherwise
        burn the whole timeout before the run was recorded as failed.
        """
        assert 'Cannot find input file' in run.CT_ERROR_PATTERNS

    @pytest.mark.parametrize('pattern', run.CT_ERROR_PATTERNS)
    def test_error_pattern_sets_error_code_and_skips_parsing(self, pattern, tmp_path, monkeypatch):
        """Test that a matched error pattern flags the run and skips output parsing."""
        # pexpect's expect() returns the index into [EOF, TIMEOUT] + CT_ERROR_PATTERNS.
        error_code = run.CT_ERROR_PATTERNS.index(pattern) + 2
        process = Mock()
        process.expect.return_value = error_code
        monkeypatch.setattr(run.pexp, 'spawn', Mock(return_value=process))

        input_file = Mock()
        input_file.path = tmp_path / 'test.in'

        run.crunchtope(input_file, 0, 10, tmp_path)

        assert input_file.error_code == error_code
        input_file.get_results.assert_not_called()

    def test_successful_run_parses_results(self, tmp_path, monkeypatch):
        """Test that reaching EOF without an error pattern parses the outputs."""
        process = Mock()
        process.expect.return_value = 0        # pexpect.EOF
        monkeypatch.setattr(run.pexp, 'spawn', Mock(return_value=process))

        input_file = Mock()
        input_file.path = tmp_path / 'test.in'

        run.crunchtope(input_file, 0, 10, tmp_path)

        input_file.get_results.assert_called_once()

    def test_timeout_sets_error_code(self, tmp_path, monkeypatch):
        """Test that a timeout flags the run and skips output parsing."""
        process = Mock()
        process.expect.return_value = 1        # pexpect.TIMEOUT
        monkeypatch.setattr(run.pexp, 'spawn', Mock(return_value=process))

        input_file = Mock()
        input_file.path = tmp_path / 'test.in'

        run.crunchtope(input_file, 0, 10, tmp_path)

        assert input_file.error_code == 1
        input_file.get_results.assert_not_called()


class TestStageZones:
    """Tests for reading a stage's grid out of its input file."""

    @staticmethod
    def _stage(zones):
        stage = Mock()
        block = Mock()
        block.contents = {'xzones': zones} if zones is not None else {}
        stage.keyword_blocks = {'DISCRETIZATION': block}
        return stage

    def test_zones_and_count(self):
        stage = self._stage(['4', '10.0', '12', '2.5', '4', '7.5'])

        assert run.stage_zones(stage) == ['4', '10.0', '12', '2.5', '4', '7.5']
        assert run.stage_nx(stage) == 20

    def test_no_xzones(self):
        assert run.stage_zones(self._stage(None)) is None
        assert run.stage_nx(self._stage(None)) is None

    def test_no_discretization_block(self):
        stage = Mock()
        stage.keyword_blocks = {}

        assert run.stage_zones(stage) is None
        assert run.stage_nx(stage) is None


class TestRegridBetweenStages:
    """Tests for resampling the restart file between two stages of a chain."""

    @staticmethod
    def _stage(zones, save_restart=None, restart_dir=None, porosity=None):
        stage = Mock()
        discretization, runtime, porosity_block = Mock(), Mock(), Mock()
        discretization.contents = {'xzones': zones}
        runtime.contents = {'save_restart': [save_restart]} if save_restart else {}
        porosity_block.contents = {'read_PorosityFile': [porosity]} if porosity else {}
        stage.keyword_blocks = {'DISCRETIZATION': discretization, 'RUNTIME': runtime,
                                'POROSITY': porosity_block}
        stage.path = None
        return stage

    def test_same_grid_is_a_no_op(self, tmp_path):
        """A chain that does not change resolution must be left exactly as it was."""
        stages = {0: self._stage(['10', '10.0'], 'r.rst'), 1: self._stage(['10', '10.0'])}

        assert run.regrid_between_stages(stages, 1, tmp_path) is False

    def test_redistributed_cells_at_constant_nx_still_regrid(self, tmp_path, monkeypatch):
        """Same nx, different widths, is a different grid and does need resampling."""
        from omphalos import restart_file as rf

        stages = {0: self._stage(['10', '10.0'], 'r.rst'),
                  1: self._stage(['2', '20.0', '6', '6.6667', '2', '20.0'])}
        monkeypatch.setattr(rf, 'verify_identity', lambda *a, **k: True)
        monkeypatch.setattr(rf, 'dims_from_input_file', lambda f: {})
        called = {}

        def fake_regrid(path, nx_in, nx_out, out, *args, **kwargs):
            called['zones'] = (kwargs.get('zones_in'), kwargs.get('zones_out'))
            out.write_bytes(b'regridded')
            return [], []

        monkeypatch.setattr(rf, 'regrid', fake_regrid)
        (tmp_path / 'r.rst').write_bytes(b'original')

        assert run.regrid_between_stages(stages, 1, tmp_path) is True
        assert called['zones'][0] == ['10', '10.0']
        assert (tmp_path / 'r.rst').read_bytes() == b'regridded'

    def test_missing_save_restart_raises(self, tmp_path):
        """A stage that changes grid but writes no restart leaves the next one nothing to read."""
        from omphalos import restart_file as rf

        stages = {0: self._stage(['10', '10.0']), 1: self._stage(['25', '4.0'])}

        with pytest.raises(rf.RstError, match='writes no restart file'):
            run.regrid_between_stages(stages, 1, tmp_path)

    def test_unverifiable_source_refuses(self, tmp_path, monkeypatch):
        """If the source does not round-trip, its layout is not understood: do not write."""
        from omphalos import restart_file as rf

        stages = {0: self._stage(['10', '10.0'], 'r.rst'), 1: self._stage(['25', '4.0'])}
        monkeypatch.setattr(rf, 'verify_identity', lambda *a, **k: False)
        monkeypatch.setattr(rf, 'dims_from_input_file', lambda f: {})
        (tmp_path / 'r.rst').write_bytes(b'original')

        with pytest.raises(rf.RstError, match='does not round-trip'):
            run.regrid_between_stages(stages, 1, tmp_path)

        assert (tmp_path / 'r.rst').read_bytes() == b'original', 'source was modified anyway'


class TestPorosityProfile:
    """Tests for reading the porosity a stage means to impose."""

    @staticmethod
    def _stage(contents):
        stage = Mock()
        block = Mock()
        block.contents = contents
        stage.keyword_blocks = {'POROSITY': block}
        return stage

    def test_single_column_file(self, tmp_path):
        import numpy as np

        path = tmp_path / 'poro.dat'
        np.savetxt(path, np.linspace(0.3, 0.4, 10))

        profile = run._porosity_profile(self._stage({'read_PorosityFile': [str(path)]}), 10)

        assert profile[0] == pytest.approx(0.3)
        assert profile[-1] == pytest.approx(0.4)

    def test_two_column_file_takes_the_second(self, tmp_path):
        import numpy as np

        path = tmp_path / 'poro.dat'
        np.savetxt(path, np.column_stack([np.arange(10.0), np.full(10, 0.35)]))

        profile = run._porosity_profile(self._stage({'read_porosityfile': [str(path)]}), 10)

        assert profile == pytest.approx(0.35)

    def test_no_porosity_file(self):
        assert run._porosity_profile(self._stage({'fix_porosity': ['0.3']}), 10) is None

    def test_too_short_file_warns_and_declines(self, tmp_path, capsys):
        """Better to keep the resampled porosity than to inject a truncated profile."""
        import numpy as np

        path = tmp_path / 'poro.dat'
        np.savetxt(path, np.full(5, 0.3))

        assert run._porosity_profile(self._stage({'read_PorosityFile': [str(path)]}), 10) is None
        assert 'has 5 rows' in capsys.readouterr().out

    def test_missing_file_warns_and_declines(self, capsys):
        assert run._porosity_profile(self._stage({'read_PorosityFile': ['nope.dat']}), 10) is None
        assert 'could not read porosity file' in capsys.readouterr().out
