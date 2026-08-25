"""Reading a sweep: the results/conditions join, renamed groups, and runs that stopped early."""

import numpy as np
import pytest
import xarray as xr

from coeus.sweep import GROUP_ALIASES, RENAMED_GROUPS, Sweep

TIMES = [1.0, 10.0, 20.0, 30.0, 43.0]


def write_sweep(directory, group='totcon', runs=4, stop_after=None, conditions=True):
    """Write a minimal results.nc, optionally with runs that stopped early.

    Mirrors the real shape: (file_num, time, X, Y, Z), with the time coordinate shared across runs
    because a sweep is concatenated along file_num. A run that stopped early is therefore padded
    with NaN rather than given a shorter axis, which is exactly what completeness() has to see
    through.

    Args:
        stop_after: {file_num: number of times that run produced}, for the runs that fell short.
    """
    stop_after = stop_after or {}
    shape = (runs, len(TIMES), 3, 1, 1)
    values = np.arange(np.prod(shape), dtype=float).reshape(shape)

    for run, produced in stop_after.items():
        values[run, produced:, :, :, :] = np.nan

    results = xr.Dataset(
        {'SO4--': (('file_num', 'time', 'X', 'Y', 'Z'), values)},
        coords={'file_num': list(range(runs)), 'time': TIMES,
                'X': [0.0, 1.0, 2.0], 'Y': [0.0], 'Z': [0.0]},
    )
    path = directory / 'results.nc'
    results.to_netcdf(path, group=group, mode='w')

    if conditions:
        xr.Dataset(
            {'rate': ('file_num', [10.0 * (index + 1) for index in range(runs)]),
             'fixed': ('file_num', [7.0] * runs)},
            coords={'file_num': list(range(runs))},
        ).to_netcdf(directory / 'conditions.nc', group='aqueous_kinetics', mode='w')

    return path


class TestRenamedGroups:
    """The same quantity is 'totcon' in a 1.x build and 'Aq_totconc' in v2.10 and v3."""

    def test_the_old_name_finds_a_new_build_file(self, tmp_path):
        write_sweep(tmp_path, group='Aq_totconc')

        assert Sweep(tmp_path / 'results.nc').resolve('totcon') == 'Aq_totconc'

    def test_the_new_name_finds_an_old_build_file(self, tmp_path):
        write_sweep(tmp_path, group='totcon')

        assert Sweep(tmp_path / 'results.nc').resolve('Aq_totconc') == 'totcon'

    def test_a_name_the_file_uses_is_returned_unchanged(self, tmp_path):
        write_sweep(tmp_path, group='totcon')

        assert Sweep(tmp_path / 'results.nc').resolve('totcon') == 'totcon'

    def test_data_is_reachable_under_either_spelling(self, tmp_path):
        write_sweep(tmp_path, group='Aq_totconc')
        sweep = Sweep(tmp_path / 'results.nc')

        assert sweep.data('totcon') is sweep.data('Aq_totconc')

    def test_an_unknown_group_says_what_is_present(self, tmp_path):
        write_sweep(tmp_path, group='totcon')

        with pytest.raises(KeyError, match='totcon'):
            Sweep(tmp_path / 'results.nc').data('nonexistent')

    def test_every_rename_resolves_both_ways(self):
        for old, new in RENAMED_GROUPS.items():
            assert GROUP_ALIASES[old] == new
            assert GROUP_ALIASES[new] == old


class TestCompleteness:
    """A sweep can fail without looking like it failed."""

    def test_a_sweep_that_finished_is_all_complete(self, tmp_path):
        write_sweep(tmp_path, runs=4)

        assert all(done for _, done in Sweep(tmp_path / 'results.nc').completeness().values())

    def test_a_short_run_is_caught(self, tmp_path):
        # Run 2 stopped after the second output time, i.e. day 10 of 43 -- the exact shape of the
        # v3 sweep that reported no errors and had truncated every run.
        write_sweep(tmp_path, runs=4, stop_after={2: 2})
        completeness = Sweep(tmp_path / 'results.nc').completeness()

        assert completeness[2] == (10.0, False)
        assert completeness[0] == (43.0, True)

    def test_the_time_coordinate_alone_would_not_have_caught_it(self, tmp_path):
        """The padded run still carries the full time axis, which is why the data has to be read."""
        write_sweep(tmp_path, runs=4, stop_after={2: 2})
        data = Sweep(tmp_path / 'results.nc').data('totcon')

        assert list(data['time'].values) == TIMES

    def test_several_short_runs_are_all_reported(self, tmp_path):
        write_sweep(tmp_path, runs=4, stop_after={1: 3, 2: 2, 3: 1})
        completeness = Sweep(tmp_path / 'results.nc').completeness()

        assert [completeness[run][0] for run in range(4)] == [43.0, 20.0, 10.0, 1.0]

    def test_a_uniformly_short_sweep_reads_as_complete(self, tmp_path):
        """With nothing to compare against, every run reaching the same time looks finished.

        Worth pinning: the target is the furthest any run got, not the time the deck asked for, so
        a sweep where everything stopped together cannot be detected here. describe() has to say
        what time was reached so the reader can judge it against the deck.
        """
        write_sweep(tmp_path, runs=4, stop_after={0: 2, 1: 2, 2: 2, 3: 2})
        completeness = Sweep(tmp_path / 'results.nc').completeness()

        assert all(done for _, done in completeness.values())
        assert all(time == 10.0 for time, _ in completeness.values())


class TestParameters:
    """What each run was given lives in a separate file and has to be joined."""

    def test_conditions_are_found_alongside_the_results(self, tmp_path):
        write_sweep(tmp_path)

        assert Sweep(tmp_path / 'results.nc').conditions_path == tmp_path / 'conditions.nc'

    def test_only_the_parameters_that_move_are_reported_as_varied(self, tmp_path):
        write_sweep(tmp_path, runs=4)
        varied = Sweep(tmp_path / 'results.nc').varied()

        assert 'aqueous_kinetics/rate' in varied
        assert 'aqueous_kinetics/fixed' not in varied

    def test_the_varied_values_line_up_with_the_runs(self, tmp_path):
        write_sweep(tmp_path, runs=4)

        assert Sweep(tmp_path / 'results.nc').varied()['aqueous_kinetics/rate'] == \
            [10.0, 20.0, 30.0, 40.0]

    def test_a_sweep_without_conditions_still_reads(self, tmp_path):
        write_sweep(tmp_path, conditions=False)
        sweep = Sweep(tmp_path / 'results.nc')

        assert sweep.conditions_path is None
        assert sweep.parameters == {}
        assert sweep.varied() == {}
        assert sweep.runs == [0, 1, 2, 3]


class TestFailuresFromTheRunLog:
    """The only signal that survives a sweep where every run was killed together."""

    SUMMARY = ('Files that failed during the run (8), as run: error_code: '
               '{0: 1, 1: 1, 2: 1, 3: 1, 4: 1, 5: 1, 6: 1, 7: 1}\n')

    def test_the_summary_line_is_read(self, tmp_path):
        write_sweep(tmp_path)
        (tmp_path / 'sweep.log').write_text(self.SUMMARY)

        assert Sweep(tmp_path / 'results.nc').failures() == {run: 1 for run in range(8)}

    def test_a_clean_log_reports_nothing(self, tmp_path):
        write_sweep(tmp_path)
        (tmp_path / 'sweep.log').write_text('Files compiled: 8 of 8.\n')

        assert Sweep(tmp_path / 'results.nc').failures() == {}

    def test_per_file_messages_are_the_fallback(self, tmp_path):
        """A run killed before writing its summary still names its failures one at a time."""
        write_sweep(tmp_path)
        (tmp_path / 'sweep.log').write_text('File 1 timed out.\nError in file 3: "bad thing".\n')
        failures = Sweep(tmp_path / 'results.nc').failures()

        assert failures[1] == 1
        assert 3 in failures

    def test_no_log_is_not_a_failure(self, tmp_path):
        write_sweep(tmp_path)
        sweep = Sweep(tmp_path / 'results.nc')

        assert sweep.log_path is None
        assert sweep.failures() == {}

    def test_a_uniformly_killed_sweep_is_caught_by_the_log_alone(self, tmp_path):
        """The gap completeness() cannot close, and the reason the log is read at all."""
        write_sweep(tmp_path, runs=8, stop_after={run: 2 for run in range(8)})
        (tmp_path / 'sweep.log').write_text(self.SUMMARY)
        sweep = Sweep(tmp_path / 'results.nc')

        assert all(done for _, done in sweep.completeness().values())
        assert len(sweep.failures()) == 8


class TestUnits:

    def test_units_come_back_for_either_spelling(self):
        from coeus.sweep import units

        assert units('totcon') == 'mol/kgw'
        assert units('Aq_totconc') == 'mol/kgw'

    def test_a_group_whose_title_states_no_unit_returns_none(self):
        """Better a bare axis label than an invented one."""
        from coeus.sweep import units

        assert units('pH') is None
        assert units('MassFraction') is None


class TestDescribe:

    def test_it_names_the_short_runs(self, tmp_path, capsys):
        from coeus.sweep import describe

        write_sweep(tmp_path, runs=4, stop_after={2: 2})
        describe(tmp_path / 'results.nc')
        printed = capsys.readouterr().out

        assert 'INCOMPLETE' in printed
        assert 'run 2: stopped at 10' in printed

    def test_it_reports_a_failure_the_data_does_not_show(self, tmp_path, capsys):
        from coeus.sweep import describe

        write_sweep(tmp_path, runs=4)
        (tmp_path / 'sweep.log').write_text(
            'Files that failed during the run (1), as run: error_code: {2: 1}\n')
        describe(tmp_path / 'results.nc')
        printed = capsys.readouterr().out

        assert 'RUN LOG REPORTS 1 FAILURES' in printed
        assert 'run 2: timed out' in printed

    def test_it_says_what_was_swept(self, tmp_path, capsys):
        from coeus.sweep import describe

        write_sweep(tmp_path, runs=4)
        describe(tmp_path / 'results.nc')
        printed = capsys.readouterr().out

        assert 'aqueous_kinetics/rate' in printed
        assert 'aqueous_kinetics/fixed' not in printed

    def test_it_accepts_a_sweep_as_well_as_a_path(self, tmp_path, capsys):
        from coeus.sweep import describe

        write_sweep(tmp_path)
        describe(Sweep(tmp_path / 'results.nc'))

        assert 'runs' in capsys.readouterr().out


class TestBasics:

    def test_a_missing_results_file_is_refused(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            Sweep(tmp_path / 'absent.nc')

    def test_the_runs_are_listed(self, tmp_path):
        write_sweep(tmp_path, runs=3)

        assert Sweep(tmp_path / 'results.nc').runs == [0, 1, 2]

    def test_datasets_are_cached(self, tmp_path):
        write_sweep(tmp_path)
        sweep = Sweep(tmp_path / 'results.nc')

        assert sweep.data('totcon') is sweep.data('totcon')
