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
from tests.unit.test_sweep import write_sweep  # noqa: E402


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
