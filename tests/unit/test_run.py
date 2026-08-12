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

        CrunchTope waits on stdin when it cannot open the deck, which would otherwise burn the
        whole timeout before the run was recorded as failed. It loses the deck either because the
        path contained a space or because it was long enough to overrun CrunchTope's buffer.
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

    def test_command_passes_the_deck_by_name_not_by_path(self, tmp_path, monkeypatch):
        """pexpect splits the command on whitespace, so an absolute path with a space in it
        reaches CrunchTope truncated at the first one. Since the deck sits in tmp_dir and
        pexpect is given cwd=tmp_dir, only the basename is needed -- and it is also the
        shortest form, which keeps clear of CrunchTope's fixed-length path buffer."""
        directory = tmp_path / 'a directory with spaces' / 'a model'
        directory.mkdir(parents=True)
        spawn = Mock(return_value=Mock(expect=Mock(return_value=0)))
        monkeypatch.setattr(run.pexp, 'spawn', spawn)

        input_file = Mock()
        input_file.path = directory / 'column.in'

        run.crunchtope(input_file, 0, 10, directory)

        command = spawn.call_args.args[0]
        assert command.endswith(' column.in')
        assert ' ' not in command.split()[-1], 'the deck argument must survive splitting'
        assert str(directory) not in command, 'the directory is passed as cwd, not in the command'
        assert spawn.call_args.kwargs['cwd'] == str(directory)

    def test_spinup_offsets_the_output_file_numbering(self, tmp_path):
        """A chain restarting stage 0 from a spinup does not begin its output at *1.tec.

        restart.F90 restores nint and CrunchTope writes that number on the tecplot files, so
        parsing from 1 looks for outputs that were never written and ends up with nothing to
        concatenate.
        """
        from pathlib import Path
        from types import SimpleNamespace

        from omphalos import restart_file as rf

        fixture = Path(__file__).resolve().parents[1] / 'restart_test' / 'sukinda10.rst'
        nint = int(rf.stored_counters(fixture)['nint'])
        staged = tmp_path / 'spinup.rst'
        staged.write_bytes(fixture.read_bytes())

        stage = SimpleNamespace(keyword_blocks={
            'RUNTIME': SimpleNamespace(contents={'restart': ['spinup.rst', 'append']})})

        assert run._spinup_file_offset(stage, tmp_path) == nint - 1

    def test_cold_stage_zero_takes_no_offset(self, tmp_path):
        from types import SimpleNamespace

        stage = SimpleNamespace(keyword_blocks={'RUNTIME': SimpleNamespace(contents={})})

        assert run._spinup_file_offset(stage, tmp_path) == 0

    def test_missing_spinup_warns_and_assumes_no_offset(self, tmp_path, capsys):
        from types import SimpleNamespace

        stage = SimpleNamespace(keyword_blocks={
            'RUNTIME': SimpleNamespace(contents={'restart': ['absent.rst', 'append']})})

        assert run._spinup_file_offset(stage, tmp_path) == 0
        assert 'absent.rst' in capsys.readouterr().out

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
    def _stage(zones, save_restart=None, restart_dir=None, porosity=None, restart=None):
        stage = Mock()
        discretization, runtime, porosity_block = Mock(), Mock(), Mock()
        discretization.contents = {'xzones': zones}
        runtime.contents = {'save_restart': [save_restart]} if save_restart else {}
        if restart:
            runtime.contents['restart'] = [restart, 'append']
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

    def test_regrid_writes_the_name_the_next_stage_reads(self, tmp_path, monkeypatch):
        """The resampled copy goes where the deck points, leaving the coarse file at its own name.

        The hazard this closes: a source left holding the *next* stage's resolution under a name
        that says otherwise, which a .rst cannot contradict and Fortran will not refuse.
        """
        from omphalos import restart_file as rf

        stages = {0: self._stage(['10', '10.0'], 'r.rst'),
                  1: self._stage(['25', '4.0'], restart='r_nx25.rst')}
        monkeypatch.setattr(rf, 'verify_identity', lambda *a, **k: True)
        monkeypatch.setattr(rf, 'dims_from_input_file', lambda f: {})
        def fake_regrid(path, nx_in, nx_out, out, *args, **kwargs):
            out.write_bytes(b'fine')
            return [], []

        monkeypatch.setattr(rf, 'regrid', fake_regrid)
        (tmp_path / 'r.rst').write_bytes(b'coarse')

        assert run.regrid_between_stages(stages, 1, tmp_path) is True
        assert (tmp_path / 'r_nx25.rst').read_bytes() == b'fine'
        assert (tmp_path / 'r.rst').read_bytes() == b'coarse', 'the coarse file was overwritten'

    def test_no_temp_file_is_left_behind(self, tmp_path, monkeypatch):
        """A failed regrid must not leave its scratch file next to the real ones."""
        from omphalos import restart_file as rf

        stages = {0: self._stage(['10', '10.0'], 'r.rst'),
                  1: self._stage(['25', '4.0'], restart='r_nx25.rst')}
        monkeypatch.setattr(rf, 'verify_identity', lambda *a, **k: True)
        monkeypatch.setattr(rf, 'dims_from_input_file', lambda f: {})

        def exploding_regrid(path, nx_in, nx_out, out, *args, **kwargs):
            out.write_bytes(b'partial')
            raise rf.RstError('boom')

        monkeypatch.setattr(rf, 'regrid', exploding_regrid)
        (tmp_path / 'r.rst').write_bytes(b'coarse')

        with pytest.raises(rf.RstError, match='boom'):
            run.regrid_between_stages(stages, 1, tmp_path)

        assert not list(tmp_path.glob('*.regrid.tmp'))
        assert (tmp_path / 'r.rst').read_bytes() == b'coarse'


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


class TestSnapToGrid:
    """Tests for placing one stage's cells on another stage's grid."""

    @staticmethod
    def _dataset(x_values, fill=1.0):
        import numpy as np
        import xarray as xr

        return xr.Dataset(
            {'C': (('time', 'X'), np.full((1, len(x_values)), fill))},
            coords={'time': [0.0], 'X': np.asarray(x_values, dtype=float)},
        )

    def test_identical_grid_is_returned_unchanged(self):
        dataset = self._dataset([5.0, 15.0, 25.0])

        assert run.snap_to_grid(dataset, dataset['X'].values) is dataset

    def test_values_land_on_the_nearest_target_cell(self):
        import numpy as np

        coarse = self._dataset([5.0, 15.0])
        target = np.array([2.5, 7.5, 12.5, 17.5])

        snapped = run.snap_to_grid(coarse, target)

        assert list(snapped['X'].values) == [2.5, 7.5, 12.5, 17.5]
        # 5.0 is equidistant from 2.5 and 7.5, so argmin takes the first; 15.0 -> 12.5 or 17.5.
        assert np.sum(~np.isnan(snapped['C'].values)) == 2

    def test_uncovered_cells_are_nan(self):
        import numpy as np

        snapped = run.snap_to_grid(self._dataset([50.0]), np.array([10.0, 30.0, 50.0, 70.0]))
        row = snapped['C'].isel(time=0).values

        assert row[2] == 1.0
        assert np.isnan(row[[0, 1, 3]]).all()

    def test_nothing_is_interpolated_between_cells(self):
        """The failure mode to avoid: reindex(method='nearest') would fill every target cell."""
        import numpy as np

        snapped = run.snap_to_grid(self._dataset([25.0, 75.0]), np.linspace(5, 95, 10))

        assert np.sum(~np.isnan(snapped['C'].values)) == 2, 'values were spread, not scattered'

    def test_collision_is_refused(self):
        """Two source cells on one target cell would silently discard one of them."""
        import numpy as np

        fine = self._dataset([10.0, 11.0, 12.0])

        assert run.snap_to_grid(fine, np.array([11.0, 90.0])) is None


class TestAlignStageGrids:
    """Tests for choosing the grid a chain's results are reported on."""

    @staticmethod
    def _dataset(n, length=100.0, fill=1.0):
        import numpy as np
        import xarray as xr

        edges = np.linspace(0, length, n + 1)
        return xr.Dataset(
            {'C': (('time', 'X'), np.full((1, n), fill))},
            coords={'time': [0.0], 'X': 0.5 * (edges[:-1] + edges[1:])},
        )

    def test_matching_grids_are_untouched(self):
        datasets = [self._dataset(10), self._dataset(10)]

        aligned, finest = run._align_stage_grids(datasets)

        assert aligned is datasets
        assert finest == 0

    def test_finest_grid_wins(self):
        """The stage a refinement chain exists to produce must stay dense on its own grid."""
        import numpy as np

        datasets = [self._dataset(10), self._dataset(40)]

        aligned, finest = run._align_stage_grids(datasets)

        assert finest == 1
        assert aligned[1].sizes['X'] == 40
        assert np.sum(~np.isnan(aligned[1]['C'].values)) == 40, 'the fine stage has holes'
        assert np.sum(~np.isnan(aligned[0]['C'].values)) == 10

    def test_finest_grid_wins_regardless_of_stage_order(self):
        """A chain that coarsens still reports on the finest grid it produced."""
        datasets = [self._dataset(40), self._dataset(10)]

        _, finest = run._align_stage_grids(datasets)

        assert finest == 0

    def test_union_is_kept_when_snapping_would_collide(self, capsys):
        import numpy as np
        import xarray as xr

        # Three cells packed inside one cell of the target grid: they cannot all be placed. The
        # target is the widest-spread stage, so the clustered one is the one that cannot be snapped.
        clustered = xr.Dataset({'C': (('time', 'X'), np.ones((1, 3)))},
                               coords={'time': [0.0], 'X': np.array([50.0, 50.1, 50.2])})
        datasets = [clustered, self._dataset(10)]

        aligned, finest = run._align_stage_grids(datasets)

        assert aligned is datasets
        assert finest is None
        assert 'do not nest' in capsys.readouterr().out


class TestConcatStagedResults:
    """Tests for collecting a chain's stages into one result set."""

    @staticmethod
    def _stage(results):
        stage = Mock()
        stage.results = results
        return stage

    @staticmethod
    def _dataset(n, time, fill=1.0):
        import numpy as np
        import xarray as xr

        edges = np.linspace(0, 100.0, n + 1)
        return xr.Dataset(
            {'C': (('time', 'X'), np.full((1, n), fill))},
            coords={'time': [time], 'X': 0.5 * (edges[:-1] + edges[1:])},
        )

    def test_same_grid_goes_to_the_first_stage(self):
        """Unchanged behaviour for a chain that does not change resolution."""
        stages = {0: self._stage({'totcon': self._dataset(10, 1.0)}),
                  1: self._stage({'totcon': self._dataset(10, 2.0)})}

        host = run.concat_staged_results(stages)

        assert host == 0
        assert list(stages[host].results['totcon'].time.values) == [1.0, 2.0]
        assert stages[host].results['totcon'].sizes['X'] == 10

    def test_differing_grids_go_to_the_finest_stage(self):
        """The returned InputFile must describe the grid its results are on."""
        import numpy as np

        stages = {0: self._stage({'totcon': self._dataset(10, 1.0)}),
                  1: self._stage({'totcon': self._dataset(40, 2.0)})}

        host = run.concat_staged_results(stages)

        assert host == 1
        results = stages[1].results['totcon']
        assert results.sizes['X'] == 40
        assert np.sum(~np.isnan(results.isel(time=1)['C'].values)) == 40
        assert np.sum(~np.isnan(results.isel(time=0)['C'].values)) == 10

    def test_a_category_only_a_later_stage_produced_survives(self):
        """Reading the categories off the first stage alone would drop it."""
        stages = {0: self._stage({'totcon': self._dataset(10, 1.0)}),
                  1: self._stage({'totcon': self._dataset(10, 2.0),
                                  'volume': self._dataset(10, 2.0)})}

        host = run.concat_staged_results(stages)

        assert 'volume' in stages[host].results

    def test_single_stage_with_results_is_left_alone(self):
        """A chain whose later stages failed keeps what the one that ran produced."""
        stages = {0: self._stage({'totcon': self._dataset(10, 1.0)}), 1: self._stage({})}

        assert run.concat_staged_results(stages) == 0

    def test_no_results_at_all(self):
        stages = {0: self._stage({}), 1: self._stage({})}

        assert run.concat_staged_results(stages) == 0


class TestTwoDimensionalStartupFailures:
    """Tests for the two 2-D startup failures the short-course exercises turn up.

    Both are worth catching for opposite reasons. The Hindmarsh solver message ends in a prompt that
    CrunchTope waits on, and pexpect gives the child a pty, so the read blocks and the run burns its
    whole timeout. The missing-K-range message is the other way round: CrunchTope prints it and
    exits, so pexpect sees EOF, the run is recorded as a success, and get_results is then asked to
    parse a directory with no tecplot output in it.
    """

    def test_hindmarsh_in_2d_is_an_error_pattern(self):
        """Test that the solver-switch prompt is caught rather than waited on."""
        assert 'Return to continue' in run.CT_ERROR_PATTERNS

    def test_missing_k_range_on_a_pressure_zone_is_an_error_pattern(self):
        """Test that a FLOW zone entry without its K range is caught."""
        assert 'No Z location for pressure' in run.CT_ERROR_PATTERNS

    @pytest.mark.parametrize('pattern', ['Return to continue', 'No Z location for pressure'])
    def test_neither_is_recorded_as_a_successful_run(self, pattern, tmp_path, monkeypatch):
        """Test that matching either one flags the file and does not parse outputs."""
        error_code = run.CT_ERROR_PATTERNS.index(pattern) + 2
        process = Mock()
        process.expect.return_value = error_code
        monkeypatch.setattr(run.pexp, 'spawn', Mock(return_value=process))

        input_file = Mock()
        input_file.path = tmp_path / 'test.in'
        run.crunchtope(input_file, 0, 10, tmp_path)

        assert input_file.error_code == error_code
        input_file.get_results.assert_not_called()


class TestFailedRunsAreCleanedUp:
    """Tests that a CrunchTope left waiting on stdin is killed rather than left resident.

    Matching the pattern is only half the job: several of these are printed by a CrunchTope that then
    blocks on a pty read, and without an explicit close it survives for the rest of the sweep, one
    per failed file.
    """

    @staticmethod
    def _run(expect_value, tmp_path, monkeypatch):
        process = Mock()
        process.expect.return_value = expect_value
        monkeypatch.setattr(run.pexp, 'spawn', Mock(return_value=process))
        input_file = Mock()
        input_file.path = tmp_path / 'test.in'
        run.crunchtope(input_file, 0, 10, tmp_path)
        return process

    def test_error_pattern_closes_the_process(self, tmp_path, monkeypatch):
        """Test that a matched error pattern forces the child closed."""
        process = self._run(2, tmp_path, monkeypatch)      # first entry of CT_ERROR_PATTERNS
        process.close.assert_called_once_with(force=True)

    def test_timeout_closes_the_process(self, tmp_path, monkeypatch):
        """Test that a timed-out run forces the child closed too."""
        process = self._run(1, tmp_path, monkeypatch)      # pexpect.TIMEOUT
        process.close.assert_called_once_with(force=True)

    def test_successful_run_is_left_alone(self, tmp_path, monkeypatch):
        """Test that a clean EOF is not force-closed, so results are parsed as before."""
        process = self._run(0, tmp_path, monkeypatch)      # pexpect.EOF
        process.close.assert_not_called()

    def test_a_close_failure_does_not_break_the_run(self, tmp_path, monkeypatch):
        """Test that cleanup problems are reported rather than raised."""
        process = Mock()
        process.expect.return_value = 2
        process.close.side_effect = OSError('no such process')
        monkeypatch.setattr(run.pexp, 'spawn', Mock(return_value=process))
        input_file = Mock()
        input_file.path = tmp_path / 'test.in'

        run.crunchtope(input_file, 0, 10, tmp_path)        # must not raise

        assert input_file.error_code == 2
