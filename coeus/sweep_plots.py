"""Plot a sweep with the sweep axis shown whole.

These take a `Sweep` and draw every run at once, rather than one at a time. That is the point of the
module: a sweep is run to compare across `file_num`, and a control that steps through runs one by
one hides exactly what was being asked. Per-run detail is available -- `field` draws a single run,
because a 2-D map cannot be overlaid -- but it is the exception rather than the default.

Surveying the twelve demo notebooks, the most common figure by a wide margin, appearing in every one
of them, is a profile along the column at one time with a line per run labelled by whatever was
swept. That is `profiles`, and the rest of this module is the next few shapes down.

Nothing here imports ipywidgets. The widget layer in topepan calls these, so a broken widget stack
costs convenience and never capability, and Omphalos itself stays installable somewhere headless.

Axis labels follow the house convention of `quantity (units)`, with the units taken from the .tec
TITLE line via `coeus.sweep.units`; a group whose TITLE names no unit is labelled bare rather than
given an invented one. Nothing here sets a font size, line width or marker size -- those belong to
the stylesheet.
"""

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from coeus.sweep import Sweep, axis_name, profile_axis, split_units, time_name, units

STYLE = Path.home() / 'Python' / 'mpl_styles' / 'publication.mplstyle'


def use_style():
    """Apply the project stylesheet, if it is where it is expected.

    Loaded by full path rather than by name because MPLCONFIGDIR is not reliably set outside an
    interactive session -- a subprocess or a `conda run` will not see a style registered by name.
    """
    if STYLE.exists():
        plt.style.use(str(STYLE))

        return True

    return False


def label_panels(axes, letters=None, x=0.03, y=0.97):
    """Letter a row of axes A, B, C ... in the top left."""
    axes = np.atleast_1d(axes).ravel()
    letters = letters or 'ABCDEFGHIJKL'

    for axis, letter in zip(axes, letters):
        axis.text(x, y, letter, transform=axis.transAxes, fontweight='bold', va='top', ha='left')


def _key(value):
    """Make a swept value comparable, whatever xarray handed back."""
    return tuple(_key(item) for item in value) if isinstance(value, list) else value


def chosen_parameter(sweep, parameter=None):
    """The swept parameter a plot should label and title itself by, or None if nothing varied."""
    varied = sweep.varied()

    if parameter is not None or not varied:
        return parameter

    return max(varied, key=lambda name: len({_key(value) for value in varied[name]}))


def short_name(parameter):
    """The tail of a parameter path, for a legend title or an axis label.

    conditions.nc names a parameter by its keyword block, e.g.
    'aqueous_kinetics/Sulfate34_reduction'. That is the right identifier to pass around and the
    wrong thing to print on an axis -- set as a legend title it runs across the panel letter, and
    as an x label it is clipped.
    """
    return parameter.rsplit('/', 1)[-1] if parameter else parameter


def run_labels(sweep, parameter=None, fmt='{:g}'):
    """Label each run by what was swept to produce it, as {file_num: label}.

    Args:
        sweep: The Sweep.
        parameter: Which entry of `sweep.varied()` to label by, e.g. 'aqueous_kinetics/rate'.
            Defaults to whichever varied parameter separates the most runs. A sweep is often a
            cross of two things -- ex9 crosses two rate scalings with four fractionation factors --
            and labelling by the first parameter found would then give four pairs of runs the same
            legend entry. Picking the most discriminating one keeps the legend readable, and where
            the choice matters it should be named explicitly.
        fmt: Format applied to numeric values.

    Returns:
        {file_num: label}, or {file_num: 'run N'} where nothing varies or there is no conditions.nc.
    """
    varied = sweep.varied()

    if not varied:
        return {run: f'run {run}' for run in sweep.runs}

    parameter = chosen_parameter(sweep, parameter)

    values = varied[parameter]

    return {
        run: (fmt.format(value) if isinstance(value, (int, float)) else str(value))
        for run, value in zip(sweep.runs, values)
    }


def _axis_label(group, variable):
    # MIN3P puts the unit in the variable name and CrunchTope puts it in the group's .tec TITLE, so
    # the name is asked first: where it carries one it is the more specific of the two.
    name, unit = split_units(variable)
    unit = unit or units(group)

    return f'{name} ({unit})' if unit else name


def outside_legend(axis, title=None):
    """Put the legend beside the axes rather than over the data.

    A sweep legend has one entry per run, so it is tall and lands on top of the profiles when
    matplotlib places it 'best'. Outside to the right it never covers anything and the panels stay
    the same size as each other.

    The figure has to make room for it: `constrained_layout=True` on the subplots does so, and
    `bbox_inches='tight'` does when saving. Use one or the other, not both -- together they fight
    and matplotlib gives up with 'constrained_layout not applied'.

    Beyond a dozen runs the legend is split across columns. A fifteen-run sweep in a single column
    is taller than the axes, and constrained_layout responds by shrinking the axes to nothing.
    """
    entries = len(axis.get_legend_handles_labels()[0])
    columns = max(1, -(-entries // 12))

    return axis.legend(title=title, frameon=False, loc='upper left', ncol=columns,
                       bbox_to_anchor=(1.02, 1.0), borderaxespad=0.0)


def _at(data, variable, run_index, time=-1, **fixed):
    """One run's values, with the singleton spatial axes dropped.

    `fixed` names axes in upper case whatever the file calls them, so `Z=0` selects MIN3P's `z`.
    """
    series = data[variable].isel(file_num=run_index)
    snapshots = time_name(data)

    if snapshots in series.dims:
        series = series.isel({snapshots: time})

    for name, index in fixed.items():
        resolved = axis_name(data, name)

        if resolved in series.dims:
            series = series.isel({resolved: index})

    return series.squeeze()


def profiles(sweep, group, variable, time=-1, axis=None, runs=None, parameter=None,
             along=None, y=0, z=0, legend=True, vertical=False, invert=None):
    """Profile along the column at one time, one line per run.

    The commonest figure in the demos. Runs are labelled by what was swept, so the legend says what
    distinguishes the lines rather than merely numbering them.

    A 1-D column reads either way round, and which one is wanted depends on the column rather than
    on the data: distance along the flow path goes on the x axis, but a column thought of as depth
    belongs on the y axis running downwards, with the value across the top. `vertical=True` gives
    the second, including the axis inversion and the move of the value axis to the top that the
    convention carries with it.

    Args:
        sweep: A Sweep, or a path to a results.nc.
        group: Output category, in either build's spelling.
        variable: Which variable in it, e.g. 'SO4--'.
        time: Index into the snapshot axis. Defaults to the last.
        axis: Axes to draw on. A new figure is made if omitted.
        runs: Which file_nums to draw. Defaults to all of them.
        parameter: Which swept parameter to label by. See `run_labels`.
        along: The spatial dimension to plot against, in either case. Defaults to whichever axis
            actually varies, so a column running down z is found without being named.
        y, z: Indices of the other two spatial axes.
        legend: Whether to draw the legend.
        vertical: Put the spatial axis on y and the value across the top, as a depth plot.
        invert: Whether the spatial axis runs downwards. Defaults to True when `vertical`, which is
            the depth convention, and False otherwise. Set it explicitly for a column that is not a
            depth -- a horizontal flow path drawn vertically for space reasons should not be
            upside down.

    Returns:
        The axes drawn on.
    """
    sweep = sweep if isinstance(sweep, Sweep) else Sweep(sweep)
    data = sweep.data(group)
    axis = axis or plt.subplots()[1]

    labels = run_labels(sweep, parameter)
    wanted = sweep.runs if runs is None else list(runs)
    along = profile_axis(data) if along is None else (axis_name(data, along) or along)

    if along is None:
        raise KeyError(f"group '{group}' has no spatial axis to profile along; "
                       f'its dimensions are {sorted(data.dims)}')

    distance = data[along].values
    invert = vertical if invert is None else invert
    # Hold the other two axes, whichever this file calls them. The one being profiled is dropped
    # rather than fixed, and any that is already singleton is squeezed away regardless.
    fixed = {'X': 0, 'Y': y, 'Z': z}
    fixed.pop(along.upper(), None)

    # A batch model is one cell, so its "profile" is a single point per run and a line through it
    # draws nothing at all -- an empty pair of axes that looks like a loading failure. ex8 is such
    # a sweep; its story is in the time series rather than along X.
    style = {'marker': 'o'} if len(distance) == 1 else {}

    for run in wanted:
        index = sweep.runs.index(run)
        values = _at(data, variable, index, time, **fixed)
        axis.plot(*((values, distance) if vertical else (distance, values)),
                  label=labels[run], **style)

    space = f'{along.upper()} (m)'
    value = _axis_label(sweep.resolve(group), variable)

    if vertical:
        axis.set_xlabel(value)
        axis.set_ylabel(space)
        # The value belongs across the top of a depth plot, where it is read before the profile.
        axis.xaxis.tick_top()
        axis.xaxis.set_label_position('top')
    else:
        axis.set_xlabel(space)
        axis.set_ylabel(value)
        # Put the x axis back at the bottom rather than assuming it was never moved. Drawing both
        # orientations onto one axes otherwise leaves the label up top, and `clear()` is only a
        # partial fix -- it restores the label but leaves the tick marks on the top spine.
        axis.xaxis.tick_bottom()
        axis.xaxis.set_label_position('bottom')

    if invert and not axis.yaxis_inverted():
        axis.invert_yaxis()

    if legend and len(wanted) > 1:
        outside_legend(axis, short_name(chosen_parameter(sweep, parameter)))

    return axis


def scalar_per_run(sweep, values, axis=None, parameter=None, marker='o'):
    """A number derived per run, plotted against what was swept to produce it.

    The derivation stays with the caller. What each demo reduces a run to differs every time -- a
    fitted slope, a front position, an integral, a mass-balance residual -- and there is no useful
    general form of it. This draws the result and labels the x axis with the parameter.

    Args:
        sweep: A Sweep, or a path to a results.nc.
        values: One number per run, in `sweep.runs` order, or a {file_num: value} mapping.
        parameter: Which swept parameter to plot against. See `run_labels`.
    """
    sweep = sweep if isinstance(sweep, Sweep) else Sweep(sweep)
    axis = axis or plt.subplots()[1]
    varied = sweep.varied()

    parameter = chosen_parameter(sweep, parameter)

    if isinstance(values, dict):
        runs = [run for run in sweep.runs if run in values]
        heights = [values[run] for run in runs]
    else:
        runs, heights = sweep.runs, list(values)

    if parameter is None:
        axis.plot(runs, heights, marker=marker, linestyle='none')
        axis.set_xlabel('run')
    else:
        swept = varied[parameter]
        axis.plot([swept[sweep.runs.index(run)] for run in runs], heights,
                  marker=marker, linestyle='none')
        axis.set_xlabel(short_name(parameter))

    return axis


def time_series(sweep, group, variable, axis=None, runs=None, parameter=None, legend=True,
                point=0, time_units=None):
    """A time series at one observation point, one line per run.

    Both codes write these every timestep rather than at the snapshot times, and carry `time` as a
    coordinate over `step` -- one row per run, since the steps a run takes are its own. A run that
    stopped early is padded, so the trailing NaNs are dropped rather than plotted as a gap running
    to the end of the axis.

    Args:
        point: Which observation point, where the group holds several. MIN3P writes one breakthrough
            record per observation point and stacks them on `output`; CrunchTope writes a group per
            point, so this is ignored there.
        time_units: What to put on the x axis after 'time'. Defaults to days for CrunchTope, and to
            nothing at all for MIN3P, whose output interval is set in the deck and recorded nowhere
            in the results.

    Raises:
        KeyError: if the group carries no time coordinate, which means it is a spatial group rather
            than a breakthrough one.
    """
    sweep = sweep if isinstance(sweep, Sweep) else Sweep(sweep)
    data = sweep.data(group)
    axis = axis or plt.subplots()[1]

    if 'time' not in data.coords:
        raise KeyError(f"group '{group}' records no time, so it has no series to draw; "
                       f'its dimensions are {sorted(data.dims)}')

    labels = run_labels(sweep, parameter)
    wanted = sweep.runs if runs is None else list(runs)
    steps = next((dim for dim in data['time'].dims if dim != 'file_num'), 'time')

    for run in wanted:
        index = sweep.runs.index(run)
        series = data[variable].isel(file_num=index)
        times = data['time']

        if 'file_num' in times.dims:
            times = times.isel(file_num=index)

        # Anything left besides the step axis is a stack of observation points.
        for name in [dim for dim in series.dims if dim != steps]:
            series = series.isel({name: point})

        finite = np.isfinite(np.asarray(series.values))
        axis.plot(np.asarray(times.values)[finite], np.asarray(series.values)[finite],
                  label=labels[run])

    if time_units is None and sweep.simulator == 'crunchtope':
        time_units = 'days'

    axis.set_xlabel(f'time ({time_units})' if time_units else 'time')
    axis.set_ylabel(_axis_label(sweep.resolve(group), variable))

    if legend and len(wanted) > 1:
        outside_legend(axis, short_name(chosen_parameter(sweep, parameter)))

    return axis


def field(sweep, group, variable, run, time=-1, axis=None, z=0, colorbar=True, **kwargs):
    """A 2-D map of one run -- the one shape that cannot show the sweep axis whole.

    Args:
        run: Which file_num to draw. Required, because there is no sensible default when only one
            run can be shown.
        kwargs: Passed to pcolormesh, e.g. `norm=LogNorm()`.
    """
    sweep = sweep if isinstance(sweep, Sweep) else Sweep(sweep)
    data = sweep.data(group)
    axis = axis or plt.subplots()[1]

    across, up = axis_name(data, 'X'), axis_name(data, 'Y')

    # Both axes must have real extent, not merely exist. A 1-D column carries Y and Z as singleton
    # dimensions in both codes, so testing only for their presence lets a column through to
    # pcolormesh, which fails with 'not enough values to unpack' and names nothing useful.
    if any(name is None or data.sizes[name] < 2 for name in (across, up)):
        raise KeyError(f"group '{group}' has no two axes to map; "
                       f'its dimensions are {dict(data.sizes)}')

    values = _at(data, variable, sweep.runs.index(run), time, Z=z)
    mesh = axis.pcolormesh(data[across].values, data[up].values, np.asarray(values).T, **kwargs)

    axis.set_xlabel(f'{across.upper()} (m)')
    axis.set_ylabel(f'{up.upper()} (m)')

    if colorbar:
        axis.figure.colorbar(mesh, ax=axis, label=_axis_label(sweep.resolve(group), variable))

    return axis
