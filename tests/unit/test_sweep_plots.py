"""Drawing a sweep.

Skipped wholesale where matplotlib is absent, which is the normal state of the `omphalos`
environment: the sweep engine runs headless and deliberately carries no plotting stack. Run these in
`JupyterEnv`, which has both matplotlib and pytest:

    conda run -n JupyterEnv python -m pytest tests/unit/test_sweep_plots.py
"""

import pytest

matplotlib = pytest.importorskip('matplotlib', reason='plotting stack absent (expected in omphalos)')
matplotlib.use('Agg')

import matplotlib.pyplot as plt  # noqa: E402

from coeus import sweep_plots as sp  # noqa: E402
from coeus.sweep import Sweep  # noqa: E402
from tests.unit.test_sweep import TIMES, write_min3p_sweep, write_sweep  # noqa: E402


@pytest.fixture(autouse=True)
def close_figures():
    yield
    plt.close('all')


@pytest.fixture
def crossed(tmp_path):
    """A sweep crossing a coarse parameter with a fine one, as ex9 does.

    Four runs: `rate` takes two values, `epsilon` four. Labelling by `rate` alone would give two
    pairs of runs the same legend entry, which is what makes the default choice matter.
    """
    import xarray as xr

    write_sweep(tmp_path, runs=4)
    xr.Dataset(
        {'rate': ('file_num', [1.0, 1.0, 2.0, 2.0]),
         'epsilon': ('file_num', [-15.0, -16.0, -17.0, -18.0])},
        coords={'file_num': [0, 1, 2, 3]},
    ).to_netcdf(tmp_path / 'conditions.nc', group='aqueous_kinetics', mode='w')

    return Sweep(tmp_path / 'results.nc')


class TestRunLabels:

    def test_runs_are_labelled_by_what_was_swept(self, tmp_path):
        write_sweep(tmp_path, runs=4)

        assert sp.run_labels(Sweep(tmp_path / 'results.nc')) == \
            {0: '10', 1: '20', 2: '30', 3: '40'}

    def test_the_default_separates_every_run_in_a_crossed_sweep(self, crossed):
        """`rate` would collide two pairs; `epsilon` distinguishes all four."""
        assert len(set(sp.run_labels(crossed).values())) == 4

    def test_the_chosen_parameter_is_the_discriminating_one(self, crossed):
        assert sp.chosen_parameter(crossed) == 'aqueous_kinetics/epsilon'

    def test_a_named_parameter_overrides_the_default(self, crossed):
        labels = sp.run_labels(crossed, 'aqueous_kinetics/rate')

        assert labels == {0: '1', 1: '1', 2: '2', 3: '2'}

    def test_runs_fall_back_to_numbers_without_conditions(self, tmp_path):
        write_sweep(tmp_path, runs=3, conditions=False)

        assert sp.run_labels(Sweep(tmp_path / 'results.nc')) == \
            {0: 'run 0', 1: 'run 1', 2: 'run 2'}


class TestDisplayNames:

    def test_the_block_prefix_is_dropped_for_display(self):
        assert sp.short_name('aqueous_kinetics/Sulfate34_reduction') == 'Sulfate34_reduction'

    def test_a_bare_name_is_unchanged(self):
        assert sp.short_name('rate') == 'rate'

    def test_none_survives(self):
        assert sp.short_name(None) is None


class TestProfiles:

    def test_one_line_per_run(self, tmp_path):
        write_sweep(tmp_path, runs=4)
        axis = sp.profiles(Sweep(tmp_path / 'results.nc'), 'totcon', 'SO4--')

        assert len(axis.lines) == 4

    def test_the_sweep_axis_is_shown_whole_by_default(self, tmp_path):
        """The design decision: every run at once, not one at a time."""
        write_sweep(tmp_path, runs=4)
        sweep = Sweep(tmp_path / 'results.nc')

        assert len(sp.profiles(sweep, 'totcon', 'SO4--').lines) == len(sweep.runs)

    def test_a_subset_of_runs_can_be_asked_for(self, tmp_path):
        write_sweep(tmp_path, runs=4)
        axis = sp.profiles(Sweep(tmp_path / 'results.nc'), 'totcon', 'SO4--', runs=[0, 2])

        assert len(axis.lines) == 2

    def test_the_y_label_carries_the_units(self, tmp_path):
        write_sweep(tmp_path, group='totcon')
        axis = sp.profiles(Sweep(tmp_path / 'results.nc'), 'totcon', 'SO4--')

        assert axis.get_ylabel() == 'SO4-- (mol/kgw)'

    def test_a_group_without_known_units_is_labelled_bare(self, tmp_path):
        write_sweep(tmp_path, group='pH')
        axis = sp.profiles(Sweep(tmp_path / 'results.nc'), 'pH', 'SO4--')

        assert axis.get_ylabel() == 'SO4--'

    def test_it_accepts_the_other_builds_group_name(self, tmp_path):
        write_sweep(tmp_path, group='Aq_totconc')
        axis = sp.profiles(Sweep(tmp_path / 'results.nc'), 'totcon', 'SO4--')

        assert axis.get_ylabel() == 'SO4-- (mol/kgw)'

    def test_the_legend_title_names_the_parameter_the_labels_came_from(self, crossed):
        axis = sp.profiles(crossed, 'totcon', 'SO4--')

        assert axis.get_legend().get_title().get_text() == 'epsilon'


class TestOrientation:
    """A 1-D column reads either way round, and which is wanted depends on the column."""

    def test_horizontal_puts_distance_on_x(self, tmp_path):
        write_sweep(tmp_path)
        axis = sp.profiles(Sweep(tmp_path / 'results.nc'), 'totcon', 'SO4--')

        assert axis.get_xlabel() == 'X (m)'
        assert axis.get_ylabel() == 'SO4-- (mol/kgw)'

    def test_vertical_puts_distance_on_y(self, tmp_path):
        write_sweep(tmp_path)
        axis = sp.profiles(Sweep(tmp_path / 'results.nc'), 'totcon', 'SO4--', vertical=True)

        assert axis.get_ylabel() == 'X (m)'
        assert axis.get_xlabel() == 'SO4-- (mol/kgw)'

    def test_vertical_runs_the_depth_axis_downwards(self, tmp_path):
        write_sweep(tmp_path)
        axis = sp.profiles(Sweep(tmp_path / 'results.nc'), 'totcon', 'SO4--', vertical=True)

        assert axis.yaxis_inverted()

    def test_vertical_moves_the_value_axis_to_the_top(self, tmp_path):
        write_sweep(tmp_path)
        axis = sp.profiles(Sweep(tmp_path / 'results.nc'), 'totcon', 'SO4--', vertical=True)

        assert axis.xaxis.get_label_position() == 'top'

    def test_horizontal_is_not_inverted(self, tmp_path):
        write_sweep(tmp_path)

        assert not sp.profiles(Sweep(tmp_path / 'results.nc'), 'totcon', 'SO4--').yaxis_inverted()

    def test_the_inversion_can_be_refused(self, tmp_path):
        """A horizontal flow path drawn vertically for space should not be upside down."""
        write_sweep(tmp_path)
        axis = sp.profiles(Sweep(tmp_path / 'results.nc'), 'totcon', 'SO4--',
                           vertical=True, invert=False)

        assert not axis.yaxis_inverted()
        assert axis.get_ylabel() == 'X (m)'

    def test_horizontal_labels_the_bottom(self, tmp_path):
        write_sweep(tmp_path)
        axis = sp.profiles(Sweep(tmp_path / 'results.nc'), 'totcon', 'SO4--')

        assert axis.xaxis.get_label_position() == 'bottom'

    def test_switching_back_returns_the_label_to_the_bottom(self, tmp_path):
        """Drawing both orientations onto one axes must not leave the label up top.

        `clear()` is not enough on its own: it restores the label but leaves the tick marks on the
        top spine, so the axis is put back explicitly.
        """
        write_sweep(tmp_path)
        sweep = Sweep(tmp_path / 'results.nc')
        _, axis = plt.subplots()

        sp.profiles(sweep, 'totcon', 'SO4--', axis=axis, vertical=True, legend=False)
        assert axis.xaxis.get_label_position() == 'top'

        sp.profiles(sweep, 'totcon', 'SO4--', axis=axis, vertical=False, legend=False)
        assert axis.xaxis.get_label_position() == 'bottom'
        assert not axis.xaxis._major_tick_kw.get('tick2On')

    def test_the_data_is_the_same_either_way(self, tmp_path):
        write_sweep(tmp_path)
        sweep = Sweep(tmp_path / 'results.nc')
        flat = sp.profiles(sweep, 'totcon', 'SO4--')
        _, upright = plt.subplots()
        upright = sp.profiles(sweep, 'totcon', 'SO4--', axis=upright, vertical=True)

        across, along = flat.lines[0].get_data()
        values, distance = upright.lines[0].get_data()

        assert list(across) == list(distance)
        assert list(along) == list(values)


class TestSingleCellSweep:
    """A batch model is one cell, so a profile along X is one point per run."""

    def test_a_single_point_gets_a_marker(self, tmp_path):
        """Without one the line has no length and the axes look empty, as if nothing loaded."""
        import numpy as np
        import xarray as xr

        values = np.arange(4 * len(TIMES), dtype=float).reshape(4, len(TIMES), 1, 1, 1)
        xr.Dataset(
            {'SO4--': (('file_num', 'time', 'X', 'Y', 'Z'), values)},
            coords={'file_num': list(range(4)), 'time': TIMES,
                    'X': [0.5], 'Y': [0.0], 'Z': [0.0]},
        ).to_netcdf(tmp_path / 'results.nc', group='totcon', mode='w')

        axis = sp.profiles(Sweep(tmp_path / 'results.nc'), 'totcon', 'SO4--')

        assert all(line.get_marker() not in ('', 'None') for line in axis.lines)

    def test_a_column_is_left_unmarked(self, tmp_path):
        write_sweep(tmp_path, runs=2)
        axis = sp.profiles(Sweep(tmp_path / 'results.nc'), 'totcon', 'SO4--')

        assert all(line.get_marker() in ('', 'None') for line in axis.lines)


class TestLegendPlacement:
    """A sweep legend has an entry per run, so inside the axes it sits on top of the data."""

    def test_the_legend_sits_outside_the_axes(self, crossed):
        figure, axis = plt.subplots(constrained_layout=True)
        sp.profiles(crossed, 'totcon', 'SO4--', axis=axis)
        figure.canvas.draw()

        legend = axis.get_legend().get_window_extent()

        assert legend.x0 >= axis.get_window_extent().x1

    def test_the_time_series_legend_is_placed_the_same_way(self, tmp_path):
        write_sweep(tmp_path, runs=3)
        sweep = Sweep(tmp_path / 'results.nc')
        figure, axis = plt.subplots(constrained_layout=True)
        sp.profiles(sweep, 'totcon', 'SO4--', axis=axis)
        figure.canvas.draw()

        assert axis.get_legend().get_window_extent().x0 >= axis.get_window_extent().x1

    def test_it_can_still_be_turned_off(self, crossed):
        axis = sp.profiles(crossed, 'totcon', 'SO4--', legend=False)

        assert axis.get_legend() is None


class TestScalarPerRun:

    def test_a_value_per_run_is_plotted_against_the_parameter(self, crossed):
        axis = sp.scalar_per_run(crossed, [1.0, 2.0, 3.0, 4.0])

        assert axis.get_xlabel() == 'epsilon'
        assert len(axis.lines[0].get_xdata()) == 4

    def test_a_mapping_is_accepted(self, crossed):
        axis = sp.scalar_per_run(crossed, {0: 1.0, 2: 3.0})

        assert len(axis.lines[0].get_xdata()) == 2

    def test_without_a_swept_parameter_it_falls_back_to_run_number(self, tmp_path):
        write_sweep(tmp_path, runs=3, conditions=False)
        axis = sp.scalar_per_run(Sweep(tmp_path / 'results.nc'), [1.0, 2.0, 3.0])

        assert axis.get_xlabel() == 'run'


class TestPanels:

    def test_axes_are_lettered(self):
        _, axes = plt.subplots(1, 3)
        sp.label_panels(axes)

        assert [axis.texts[0].get_text() for axis in axes] == ['A', 'B', 'C']

    def test_the_letters_are_bold(self):
        _, axes = plt.subplots(1, 2)
        sp.label_panels(axes)

        assert axes[0].texts[0].get_fontweight() == 'bold'


class TestNoWidgetDependency:

    def test_the_module_does_not_import_ipywidgets(self):
        """The layering that makes a broken widget stack survivable."""
        from pathlib import Path

        source = Path(sp.__file__).read_text()

        assert 'ipywidgets' not in source.replace('ipywidgets. The widget layer', '')


class TestMin3pPlots:
    """The same calls, against output whose axes are named differently."""

    def test_a_profile_finds_the_axis_that_varies(self, tmp_path):
        # A z column with x and y singleton: defaulting to x would draw a single point.
        sweep = Sweep(write_min3p_sweep(tmp_path, along='z', cells=5))
        axis = sp.profiles(sweep, 'gsc', 'no3-1')

        assert axis.get_xlabel() == 'Z (m)'
        assert len(axis.lines) == len(sweep.runs)
        assert len(axis.lines[0].get_xdata()) == 5

    def test_a_profile_finds_an_x_column_too(self, tmp_path):
        sweep = Sweep(write_min3p_sweep(tmp_path, along='x', cells=4))

        assert sp.profiles(sweep, 'gsc', 'no3-1').get_xlabel() == 'X (m)'

    def test_a_named_axis_is_accepted_in_either_case(self, tmp_path):
        sweep = Sweep(write_min3p_sweep(tmp_path, along='z', cells=5))

        assert sp.profiles(sweep, 'gsc', 'no3-1', along='Z').get_xlabel() == 'Z (m)'

    def test_units_are_read_out_of_the_variable_name(self, tmp_path):
        sweep = Sweep(write_min3p_sweep(tmp_path))
        axis = sp.profiles(sweep, 'gsc', 'C-Alk [eq_per_L]')

        assert axis.get_ylabel() == 'C-Alk (eq/L)'

    def test_a_crunchtope_species_keeps_its_parenthesised_state(self, tmp_path):
        # 'CO2(aq)' is a species name, not a unit, and must survive the units split intact.
        assert sp._axis_label('totcon', 'CO2(aq)') == 'CO2(aq) (mol/kgw)'

    def test_a_series_selects_one_observation_point(self, tmp_path):
        # MIN3P stacks its observation points on `output`; a line must come from one of them.
        sweep = Sweep(write_min3p_sweep(tmp_path, steps=6))
        axis = sp.time_series(sweep, 'gbc', 'na+1')

        assert len(axis.lines) == len(sweep.runs)
        assert len(axis.lines[0].get_xdata()) == 6

    def test_a_series_does_not_claim_units_min3p_never_recorded(self, tmp_path):
        sweep = Sweep(write_min3p_sweep(tmp_path))

        assert sp.time_series(sweep, 'gbc', 'na+1').get_xlabel() == 'time'

    def test_a_crunchtope_series_still_says_days(self, tmp_path):
        write_sweep(tmp_path)
        import numpy as np
        import xarray as xr
        xr.Dataset(
            {'SO4--': (('file_num', 'step'), np.zeros((4, 3)))},
            coords={'file_num': list(range(4)), 'step': [0, 1, 2],
                    'time': (('file_num', 'step'), np.tile([0.0, 1.0, 2.0], (4, 1)))},
        ).to_netcdf(tmp_path / 'results.nc', group='timeseries_influent', mode='a')

        axis = sp.time_series(Sweep(tmp_path / 'results.nc'), 'timeseries_influent', 'SO4--')

        assert axis.get_xlabel() == 'time (days)'

    def test_a_spatial_group_refuses_to_be_drawn_as_a_series(self, tmp_path):
        sweep = Sweep(write_min3p_sweep(tmp_path))

        with pytest.raises(KeyError, match='records no time'):
            sp.time_series(sweep, 'gsc', 'no3-1')

    def test_a_one_dimensional_group_refuses_to_be_mapped(self, tmp_path):
        sweep = Sweep(write_min3p_sweep(tmp_path))

        with pytest.raises(KeyError, match='no two axes'):
            sp.field(sweep, 'gsc', 'no3-1', run=0)
