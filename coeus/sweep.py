"""Read an Omphalos sweep: the results, what was varied to produce them, and whether it worked.

A sweep is spread across two files that have to be read together. `results.nc` holds the simulator
output, grouped by output category and carrying a `file_num` dimension; `conditions.nc` holds what
each `file_num` actually was -- the parameter values that run was given. Neither is much use alone,
and every analysis notebook so far has re-implemented the join by hand.

Two things make that join more awkward than it should be, and both are absorbed here.

**Output categories are renamed between CrunchTope builds.** The same physical quantity is `totcon`
in a CrunchTope 1.x derivative and `Aq_totconc` in v2.10 and v3, and there are several more pairs.
A notebook asking for `group='volume'` finds nothing in a newer-build run and fails in a way that
looks like missing data rather than a renamed group. `data()` accepts either spelling.

**A sweep can fail without looking like it failed.** Runs that time out, or that are killed partway,
still leave a `results.nc` full of plausible numbers -- just fewer timesteps than asked for. Two
sweeps this week did exactly that: one where every run hit a wall-clock timeout, and one where every
run stopped at day 10 of 43. Both read as clean output. `completeness()` compares what each run
reached against what the sweep as a whole reached, so a short run is visible rather than silent.

Nothing here plots. Omphalos runs headless on clusters and must not acquire notebook dependencies,
so the drawing lives in `coeus.sweep_plots` and the widgets that drive it live in topepan.
"""

import ast
import re
from pathlib import Path

import netCDF4
import xarray as xr

# Output categories renamed between CrunchTope builds, keyed by the older (1.x / BOGLSource2026)
# name. The newer names arrived with v2.10 and are unchanged in v3.
#
# The capitalisation here is the file's, not a tidied version of it: a group is named for the .tec
# file it came from, and neither the stem extraction in core.file_methods nor netcdf_name touches
# case. So the newer names really are CamelCase. Matching is case-insensitive as a fallback anyway,
# because these get written down by hand and get it wrong -- an earlier draft of the version audit
# recorded them lowercased, and this table was seeded from it.
RENAMED_GROUPS = {
    'conc': 'Aq_conc',
    'totcon': 'Aq_totconc',
    'volume': 'MineralVolumeFraction',
    'area': 'MineralArea',
    'rate': 'MineralRate',
    'saturation': 'MineralSaturation',
    'TotMineral': 'MineralConc',
}

# Both directions, so either spelling resolves to whatever the file actually contains.
GROUP_ALIASES = {**RENAMED_GROUPS, **{new: old for old, new in RENAMED_GROUPS.items()}}

# Units, read from the TITLE line each .tec file carries. Recorded here because the netCDF holds no
# units attribute -- checked across the demo results files, every variable reports none -- so this
# is the only place an analysis can get them from. Groups whose TITLE states no unit are left out
# rather than guessed at; see the version audit for the ones that remain unresolved.
GROUP_UNITS = {
    'conc': 'log mol/kgw',
    'totcon': 'mol/kgw',
    'area': 'm^2/m^3 PM',
    'volume': 'm^3 mineral/m^3 porous medium',
    'rate': 'mol/m^3/s',
    'saturation': 'log Q/Keq',
    'TotMineral': 'mol/m^3 PM',
    'AqRate': 'mol/L/yr',
    'exchange': 'mol/g solid',
    'totexchange': 'mol/g solid',
    'velocity': 'm/yr',
    'toperatio_aq': 'per mil',
    'toperatio_min': 'per mil',
    'temperature': 'C',
    'IonicStrength': 'mol/kgw',
    'MineralPercent': 'weight % mineral',
    'Delta_MineralVolume': 'm^3 mineral/m^3 porous medium',
}


def units(group):
    """Return the units of an output category, or None where the .tec TITLE states none.

    Accepts either build's spelling. Returning None rather than a guess is deliberate: pH, porosity,
    tortuosity and the activity of water are dimensionless, but MassFraction's TITLE says only
    'xgram' and has not been run down, so an axis label should be left bare rather than invented.
    """
    return GROUP_UNITS.get(group) or GROUP_UNITS.get(GROUP_ALIASES.get(group))


def group_names(path):
    """Return the netCDF group names in a file, in file order.

    xarray opens one group at a time and cannot enumerate them, so this drops to netCDF4.
    """
    with netCDF4.Dataset(path) as dataset:
        return list(dataset.groups.keys())


class Sweep:
    """The results of one Omphalos sweep, joined to the parameters that produced it.

    Args:
        results: Path to `results.nc`.
        conditions: Path to `conditions.nc`. Defaults to a file of that name beside the results,
            which is where Omphalos writes it.

    Attributes:
        results_path: Path to the results file.
        conditions_path: Path to the conditions file, or None if there is not one.
    """

    def __init__(self, results, conditions=None):
        self.results_path = Path(results)

        if not self.results_path.exists():
            raise FileNotFoundError(f'no results file at {self.results_path}')

        if conditions is None:
            alongside = self.results_path.parent / 'conditions.nc'
            self.conditions_path = alongside if alongside.exists() else None
        else:
            self.conditions_path = Path(conditions)

        self._cache = {}
        self._groups = None

    def __repr__(self):
        return f'Sweep({self.results_path.name}, {len(self.runs)} runs, {len(self.groups)} groups)'

    @property
    def groups(self):
        """The output categories present, under the names this file actually uses."""
        if self._groups is None:
            self._groups = group_names(self.results_path)

        return self._groups

    def resolve(self, group):
        """Return the name this file uses for an output category, whichever spelling was asked for.

        Raises:
            KeyError: if neither the requested name nor its counterpart is in the file. The message
                lists what is present, because the usual cause is asking a newer-build file for an
                older build's group name.
        """
        if group in self.groups:
            return group

        alias = GROUP_ALIASES.get(group)

        if alias in self.groups:
            return alias

        # Last resort, because these names are copied by hand and the capitalisation is easy to get
        # wrong -- 'Mineralvolumefraction' for 'MineralVolumeFraction' is a real example.
        folded = {name.casefold(): name for name in self.groups}

        for candidate in (group, alias):
            if candidate is not None and candidate.casefold() in folded:
                return folded[candidate.casefold()]

        raise KeyError(
            f"no group '{group}' in {self.results_path.name}"
            + (f" (nor its other spelling '{alias}')" if alias else '')
            + f'. Present: {sorted(self.groups)}'
        )

    def data(self, group):
        """Open an output category, accepting either build's spelling of its name.

        Datasets are cached, so repeated calls in a notebook do not re-read the file.
        """
        name = self.resolve(group)

        if name not in self._cache:
            self._cache[name] = xr.open_dataset(self.results_path, group=name)

        return self._cache[name]

    @property
    def runs(self):
        """The file_num values in the sweep, sorted."""
        for group in self.groups:
            data = self.data(group)

            if 'file_num' in data.dims:
                return [int(value) for value in data['file_num'].values]

        return []

    @property
    def parameter_groups(self):
        """The groups of conditions.nc -- one per swept keyword block, e.g. 'aqueous_kinetics'."""
        if self.conditions_path is None:
            return []

        return group_names(self.conditions_path)

    @property
    def parameters(self):
        """What each run was given, as {group: {parameter: [value per file_num]}}.

        Reads conditions.nc, which Omphalos writes with `--compile-inputs`. Returns an empty dict
        where there is no conditions file, since a sweep is still readable without one -- the runs
        just cannot be labelled by what varied.
        """
        if self.conditions_path is None:
            return {}

        found = {}

        for group in self.parameter_groups:
            with xr.open_dataset(self.conditions_path, group=group) as data:
                found[group] = {
                    name: data[name].values.tolist() for name in data.data_vars
                }

        return found

    def varied(self):
        """The parameters that actually differ across runs, as {'group/parameter': [values]}.

        conditions.nc records every parameter Omphalos could have varied, most of which hold the
        same value in every run. Only the ones that move describe the sweep, and those are what a
        run should be labelled by.
        """
        moving = {}

        for group, parameters in self.parameters.items():
            for name, values in parameters.items():
                if len(set(_hashable(value) for value in values)) > 1:
                    moving[f'{group}/{name}'] = values

        return moving

    @property
    def log_path(self):
        """Path to the run log rhea leaves beside the results, or None."""
        alongside = self.results_path.parent / 'sweep.log'

        return alongside if alongside.exists() else None

    def failures(self):
        """Which runs the run log says failed, as {file_num: error_code}.

        This is the only place a uniformly-truncated sweep gives itself away. `completeness` measures
        runs against each other, so when every run is killed at the same wall-clock limit they all
        look equally finished; the log records the timeout regardless. rhea prints a summary line
        naming every failure, and that is preferred over the individual messages because it is
        written once at the end and carries the error code rather than just the fact of a failure.

        Returns an empty dict where there is no log, which is normal: a sequential
        `omphalos` run records the same information in inputs.pkl instead, and a log may simply not
        have been kept.
        """
        if self.log_path is None:
            return {}

        text = self.log_path.read_text(errors='replace')
        summary = FAILURE_SUMMARY.search(text)

        if summary:
            try:
                return {int(run): int(code) for run, code in
                        ast.literal_eval(summary.group(1)).items()}
            except (ValueError, SyntaxError):
                pass

        # No summary -- the run may have been killed before writing one. Fall back to the per-file
        # messages, which carry no code, so the failure is recorded without claiming to know why.
        found = {int(run): 1 for run in re.findall(r'File (\d+) timed out', text)}
        found.update({int(run): None for run in re.findall(r'Error in file (\d+)', text)})

        return found

    def completeness(self):
        """How far each run got, as {file_num: (last_time, reached_the_end)}.

        A run that stops early still writes plausible output, so a short run is invisible unless it
        is compared against the others. The longest time any run reached is taken as the target:
        that is not the same as the time the deck asked for, but a sweep where every run stops at
        the same early time still shows up as a uniform stop, and one where only some stop short
        shows up as the mismatch it is.
        """
        times = self._times()

        if not times:
            return {}

        target = max(times.values())

        return {run: (last, last >= target) for run, last in times.items()}

    def _times(self):
        """The last time each run actually has data for, as {file_num: time}.

        The time coordinate is shared across runs, not per-run: a sweep is assembled by
        concatenating each run along `file_num`, so the axis is the union of every run's output
        times and a run that stopped early is padded with NaN rather than truncated. Reading the
        coordinate would therefore report every run as reaching the end. The data has to be read
        instead, and the answer is the last time at which a run holds a finite value.
        """
        for group in self.groups:
            data = self.data(group)

            if 'file_num' not in data.dims or 'time' not in data.dims or not data.data_vars:
                continue

            # Any variable will do -- a run that stopped writes nothing at all past that point, so
            # every variable goes NaN together.
            variable = data[next(iter(data.data_vars))]
            times = data['time'].values
            found = {}

            for index, run in enumerate(data['file_num'].values):
                series = variable.isel(file_num=index)
                # Collapse everything but time, so one finite cell anywhere counts as output.
                present = series.notnull().any(
                    dim=[dim for dim in series.dims if dim != 'time']
                ).values

                if present.any():
                    found[int(run)] = float(times[present.nonzero()[0][-1]])

            if found:
                return found

        return {}


def _hashable(value):
    """Make a parameter value comparable, whatever xarray handed back."""
    if isinstance(value, list):
        return tuple(_hashable(item) for item in value)

    return value


# rhea's summary of which runs failed and why, e.g.
#   Files that failed during the run (8), as run: error_code: {0: 1, 1: 1, ...}
FAILURE_SUMMARY = re.compile(r'Files that failed during the run \(\d+\), as run: error_code: (\{.*\})')

# What a non-zero error_code means, from omphalos/run.py by way of coeus.helper.filter_errors.
ERROR_CODES = {
    -1: 'exited without writing output',
    0: 'ran cleanly',
    1: 'timed out',
}


def describe(sweep, stream=None):
    """Print what is in a sweep, what was varied, and whether it actually worked.

    Written for the failure that does not announce itself. A sweep whose runs time out, or are
    killed partway, still leaves a results.nc full of plausible numbers; two sweeps this week did
    exactly that and both read as clean output. What separates them from a real result is the time
    each run reached and the run log, so both are reported here rather than left to be discovered.

    One limit is worth knowing: `completeness` measures each run against the furthest any run got,
    so a sweep where *every* run stopped at the same early time cannot be detected that way. The
    time reached is printed plainly for that reason, to be judged against what the deck asked for,
    and the run log is read because it records a timeout even when the output looks uniform.

    Args:
        sweep: A Sweep, or a path to a results.nc.
        stream: Where to write. Defaults to stdout.
    """
    if not isinstance(sweep, Sweep):
        sweep = Sweep(sweep)

    write = print if stream is None else lambda line='': print(line, file=stream)

    write(f'{sweep.results_path}')
    write(f'  {len(sweep.runs)} runs, {len(sweep.groups)} output groups')

    completeness = sweep.completeness()

    if completeness:
        reached = {run: time for run, (time, _) in completeness.items()}
        short = sorted(run for run, (_, done) in completeness.items() if not done)
        furthest = max(reached.values())

        if short:
            write(f'  INCOMPLETE: {len(short)} of {len(completeness)} runs stopped before '
                  f'{furthest:g}, the furthest any run reached')
            for run in short:
                write(f'      run {run}: stopped at {reached[run]:g}')
        else:
            write(f'  all runs reached {furthest:g} '
                  f'-- check that against the time the deck asked for')

    failures = sweep.failures()

    if failures:
        write(f'  RUN LOG REPORTS {len(failures)} FAILURES:')
        for run, code in sorted(failures.items()):
            write(f'      run {run}: {ERROR_CODES.get(code, f"error code {code}")}')
    elif sweep.log_path is not None:
        write('  run log reports no failures')

    varied = sweep.varied()

    if varied:
        write(f'  swept {len(varied)} parameter(s):')
        for name, values in varied.items():
            distinct = sorted({_hashable(value) for value in values})
            shown = ', '.join(f'{value:g}' if isinstance(value, float) else str(value)
                              for value in distinct[:6])
            write(f'      {name}: {len(distinct)} distinct value(s) [{shown}'
                  f'{", ..." if len(distinct) > 6 else ""}]')
    elif sweep.conditions_path is None:
        write('  no conditions.nc alongside, so runs cannot be labelled by what varied')
    else:
        write('  conditions.nc records no parameter that differs between runs')

    write('  groups:')
    for name in sorted(sweep.groups):
        data = sweep.data(name)
        shape = ', '.join(f'{dim}={size}' for dim, size in data.sizes.items())
        variables = list(data.data_vars)
        listed = ', '.join(variables[:4]) + (', ...' if len(variables) > 4 else '')
        write(f'      {name} ({shape}): {len(variables)} variables [{listed}]')
