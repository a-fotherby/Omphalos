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

from coeus.sweep import Sweep, units

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
    unit = units(group)

    return f'{variable} ({unit})' if unit else variable


def _at(data, variable, run_index, time=-1, **fixed):
    """One run's values, with the singleton spatial axes dropped."""
    series = data[variable].isel(file_num=run_index)

    if 'time' in series.dims:
        series = series.isel(time=time)

    for name, index in fixed.items():
        if name in series.dims:
            series = series.isel({name: index})

    return series.squeeze()


def profiles(sweep, group, variable, time=-1, axis=None, runs=None, parameter=None,
             along='X', y=0, z=0, legend=True):
    """Profile along the column at one time, one line per run.

    The commonest figure in the demos. Runs are labelled by what was swept, so the legend says what
    distinguishes the lines rather than merely numbering them.

    Args:
        sweep: A Sweep, or a path to a results.nc.
        group: Output category, in either build's spelling.
        variable: Which variable in it, e.g. 'SO4--'.
        time: Index into the time axis. Defaults to the last.
        axis: Axes to draw on. A new figure is made if omitted.
        runs: Which file_nums to draw. Defaults to all of them.
        parameter: Which swept parameter to label by. See `run_labels`.
        along: The spatial dimension to plot against.
        y, z: Indices of the other two spatial axes.
        legend: Whether to draw the legend.

    Returns:
        The axes drawn on.
    """
    sweep = sweep if isinstance(sweep, Sweep) else Sweep(sweep)
    data = sweep.data(group)
    axis = axis or plt.subplots()[1]

    labels = run_labels(sweep, parameter)
    wanted = sweep.runs if runs is None else list(runs)
    distance = data[along].values

    for run in wanted:
        index = sweep.runs.index(run)
        axis.plot(distance, _at(data, variable, index, time, Y=y, Z=z), label=labels[run])

    axis.set_xlabel(f'{along} (m)')
    axis.set_ylabel(_axis_label(sweep.resolve(group), variable))

    if legend and len(wanted) > 1:
        axis.legend(title=short_name(chosen_parameter(sweep, parameter)), frameon=False)

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


def time_series(sweep, group, variable, axis=None, runs=None, parameter=None, legend=True):
    """A time series at one observation point, one line per run.

    The `timeseries_*` groups are written every timestep rather than at the snapshot times, and
    carry `time` as a coordinate over `step`. A run that stopped early is padded, so the trailing
    NaNs are dropped rather than plotted as a gap running to the end of the axis.
    """
    sweep = sweep if isinstance(sweep, Sweep) else Sweep(sweep)
    data = sweep.data(group)
    axis = axis or plt.subplots()[1]

    labels = run_labels(sweep, parameter)
    wanted = sweep.runs if runs is None else list(runs)

    for run in wanted:
        index = sweep.runs.index(run)
        series = data[variable].isel(file_num=index)
        times = data['time']

        if 'file_num' in times.dims:
            times = times.isel(file_num=index)

        finite = np.isfinite(np.asarray(series.values))
        axis.plot(np.asarray(times.values)[finite], np.asarray(series.values)[finite],
                  label=labels[run])

    axis.set_xlabel('time (days)')
    axis.set_ylabel(_axis_label(sweep.resolve(group), variable))

    if legend and len(wanted) > 1:
        axis.legend(title=short_name(chosen_parameter(sweep, parameter)), frameon=False)

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

    values = _at(data, variable, sweep.runs.index(run), time, Z=z)
    mesh = axis.pcolormesh(data['X'].values, data['Y'].values, np.asarray(values).T, **kwargs)

    axis.set_xlabel('X (m)')
    axis.set_ylabel('Y (m)')

    if colorbar:
        axis.figure.colorbar(mesh, ax=axis, label=_axis_label(sweep.resolve(group), variable))

    return axis
