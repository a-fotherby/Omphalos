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
import pickle
import re
import warnings
from pathlib import Path

import netCDF4
import numpy as np
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


# Simulators name their axes differently, and only the names differ: CrunchTope writes X/Y/Z and a
# physical `time`, MIN3P writes x/y/z and indexes its snapshots by `output`, an integer with no
# physical value attached. Resolving the names here keeps every caller simulator-agnostic.
TIME_DIMS = ('time', 'output')


def axis_name(data, axis='X'):
    """Return the name this dataset uses for a spatial axis, or None if it has none.

    Accepts either case, so `axis_name(data, 'X')` finds MIN3P's `x`.
    """
    for candidate in (axis, axis.lower(), axis.upper()):
        if candidate in data.dims:
            return candidate

    return None


def time_name(data):
    """Return the dimension this dataset indexes snapshots by, or None.

    `time` for CrunchTope, `output` for MIN3P. A group carrying both -- MIN3P's breakthrough files
    have `output` alongside a ragged per-run `time` over `step` -- resolves to `time`, which is the
    one with physical values on it.
    """
    for candidate in TIME_DIMS:
        if candidate in data.dims:
            return candidate

    return None


def spatial_axes(data):
    """The spatial dimensions present, in x-y-z order, under the names this file uses."""
    found = (axis_name(data, axis) for axis in 'XYZ')

    return [name for name in found if name is not None]


def profile_axis(data):
    """The spatial dimension a 1-D profile should be drawn along, or None.

    Whichever axis actually varies, rather than always x: MIN3P's dissolution demo is a column
    running down `z` with `x` and `y` singleton, and plotting against x there draws a single point.
    """
    axes = spatial_axes(data)
    varying = [name for name in axes if data.sizes[name] > 1]

    return next(iter(varying or axes), None)


# A units suffix in a variable name, e.g. 'C-Alk [eq_per_L]'. Square brackets only: round ones would
# take the '(aq)' off half the species in a CrunchTope basis and call it a unit.
NAMED_UNITS = re.compile(r'^(.*?)\s*\[([^\[\]]+)\]\s*$')


def split_units(variable):
    """Split a units suffix off a variable name, as (name, units).

    MIN3P carries the unit in the variable name where CrunchTope carries it in the .tec TITLE for
    the whole group, so this is the only place a MIN3P unit can be read from -- nothing in the
    netCDF has a units attribute. Returns (variable, None) where there is no suffix.
    """
    match = NAMED_UNITS.match(variable)

    if not match:
        return variable, None

    # MIN3P spells a solidus '_per_', presumably to keep it out of filenames.
    return match.group(1), match.group(2).replace('_per_', '/')


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

        # A sweep directory is a reasonable thing to point at, and netCDF4 answers one with
        # 'NetCDF: Unknown file format', which names neither the problem nor the fix.
        if self.results_path.is_dir():
            inside = self.results_path / 'results.nc'

            if not inside.is_file():
                raise FileNotFoundError(f'{self.results_path} is a directory with no results.nc '
                                        f'in it')

            self.results_path = inside

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

    def spatial_groups(self):
        """Groups holding a field over space -- the ones a profile or a map can be drawn from."""
        return [group for group in self.groups
                if self.data(group).data_vars and spatial_axes(self.data(group))]

    def series_groups(self):
        """Groups holding a record at fixed observation points, written every timestep.

        Identified by structure rather than by name, because the names agree on nothing: CrunchTope
        calls these `timeseries_*` and MIN3P calls them `gbc`, `gbm`, `gbt`. What both do is carry
        `time` as a *coordinate* over `step`, where a spatial group carries it as a dimension of its
        own -- one row of times per run, since the steps a run takes are its own.
        """
        return [group for group in self.groups
                if self.data(group).data_vars
                and 'time' in self.data(group).coords and 'time' not in self.data(group).dims]

    def map_groups(self):
        """Groups with two spatial axes of real extent -- the ones `field` can map."""
        found = []

        for group in self.spatial_groups():
            data = self.data(group)

            if sum(data.sizes[axis] > 1 for axis in spatial_axes(data)) > 1:
                found.append(group)

        return found

    def snapshot_count(self, group):
        """How many snapshots a group holds, for sizing a control that steps through them."""
        axis = self.snapshot_axis(group)

        return 0 if axis is None else self.data(group).sizes[axis[0]]

    @property
    def simulator(self):
        """Which code wrote this sweep, as 'min3p' or 'crunchtope'.

        Nothing in the file records it, so it is read off the dimension names: MIN3P indexes its
        snapshots by `output` and names its axes in lower case, CrunchTope uses `time` and X/Y/Z.
        Used only to choose defaults the file cannot supply, such as the units of the time axis.
        """
        for group in self.groups:
            dims = self.data(group).dims

            if 'output' in dims:
                return 'min3p'

            if 'time' in dims or 'X' in dims:
                return 'crunchtope'

        return 'crunchtope'

    @property
    def parameter_groups(self):
        """The groups of conditions.nc -- one per swept keyword block, e.g. 'aqueous_kinetics'."""
        if self.conditions_path is None:
            return []

        return group_names(self.conditions_path)

    @property
    def records_path(self):
        """Path to the records.pkl a MIN3P sweep leaves beside its results, or None."""
        alongside = self.results_path.parent / 'records.pkl'

        return alongside if alongside.exists() else None

    def _record_parameters(self):
        """What each run was given, recovered from a MIN3P records.pkl.

        A MIN3P sweep writes no conditions.nc: Omphalos pickles the InputFile objects instead. So
        what varied is recovered by comparing the decks against each other token by token, which
        finds the same thing conditions.nc would have recorded -- and finds it without being told
        what the sweep was supposed to vary.

        Parameters are named `keyword[line][token]` within their block, because a MIN3P keyword can
        carry several lines and each line several values, and the sweep may have moved any one of
        them. Values are returned as floats where they parse as numbers, so a legend can format them
        and `scalar_per_run` can plot against them.
        """
        if self.records_path is None:
            return {}

        try:
            with open(self.records_path, 'rb') as handle:
                # Unpickling needs min3p.input_file importable, which it is whenever coeus is:
                # both live in the same checkout.
                records = _CompatUnpickler(handle).load()
        except Exception as problem:
            # A sweep must stay readable when its records do not: the results are the point and the
            # only thing lost is the run labels. Said out loud rather than swallowed, because
            # 'run 0, run 1' otherwise looks like a sweep that varied nothing.
            warnings.warn(f'could not read {self.records_path.name}, so runs cannot be labelled '
                          f'by what varied: {type(problem).__name__}: {problem}')

            return {}

        tokens = {int(run): _deck_tokens(record) for run, record in records.items()}

        if not tokens:
            return {}

        shared = set.intersection(*(set(found) for found in tokens.values()))
        found = {}

        for key in sorted(shared):
            values = [tokens[run].get(key) for run in self.runs if run in tokens]

            if len(set(values)) < 2:
                continue

            block, keyword, line, token = key
            found.setdefault(block, {})[f'{keyword}[{line}][{token}]'] = [
                _number(value) for value in values
            ]

        return found

    @property
    def parameters(self):
        """What each run was given, as {group: {parameter: [value per file_num]}}.

        Reads conditions.nc, which Omphalos writes with `--compile-inputs`, and falls back to the
        records.pkl a MIN3P sweep writes in its place. Returns an empty dict where there is neither,
        since a sweep is still readable without one -- the runs just cannot be labelled by what
        varied.
        """
        if self.conditions_path is None:
            return self._record_parameters()

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

    def snapshot_axis(self, group):
        """How one output category indexes its snapshots, as (dim, marks, physical), or None.

        `marks` gives the value to report for each position along `dim`, and `physical` says whether
        those values are simulated times or merely a count. Three shapes turn up:

        - CrunchTope shares one `time` coordinate across every run, so `marks` is 1-D.
        - MIN3P's breakthrough groups carry a ragged `time` over `(file_num, step)` -- each run has
          its own times -- so `marks` is 2-D and indexed by run.
        - MIN3P's spatial groups carry only `output`, a bare integer index with no coordinate values
          attached. There is no time to report, so the position is used and `physical` is False.
        """
        data = self.data(group)

        if 'file_num' not in data.dims or not data.data_vars:
            return None

        times = data['time'] if 'time' in data.coords else None

        if times is not None and times.dims == ('time',):
            return 'time', times.values, True

        if times is not None and 'file_num' in times.dims:
            axis = next((dim for dim in times.dims if dim != 'file_num'), None)

            if axis is not None:
                return axis, times.values, True

        axis = time_name(data)

        return None if axis is None else (axis, np.arange(data.sizes[axis]), False)

    def _completeness_source(self):
        """The group completeness should be read from, as (group, dim, marks, physical), or None.

        Groups indexing snapshots by simulated time are preferred over ones carrying only a count,
        so a MIN3P sweep is measured against its breakthrough times rather than its snapshot number
        whenever both are present.
        """
        candidates = [(group, self.snapshot_axis(group)) for group in self.groups]
        found = [(group, axis) for group, axis in candidates if axis is not None]

        for physical in (True, False):
            for group, (dim, marks, is_time) in found:
                if is_time is physical:
                    return group, dim, marks, is_time

        return None

    def _times(self):
        """The last time each run actually has data for, as {file_num: time}.

        The time coordinate is shared across runs, not per-run: a sweep is assembled by
        concatenating each run along `file_num`, so the axis is the union of every run's output
        times and a run that stopped early is padded with NaN rather than truncated. Reading the
        coordinate would therefore report every run as reaching the end. The data has to be read
        instead, and the answer is the last time at which a run holds a finite value.
        """
        source = self._completeness_source()

        if source is None:
            return {}

        group, axis, marks, _ = source
        data = self.data(group)
        # Any variable will do -- a run that stopped writes nothing at all past that point, so
        # every variable goes NaN together.
        variable = data[next(iter(data.data_vars))]
        marks = np.asarray(marks)
        found = {}

        for index, run in enumerate(data['file_num'].values):
            series = variable.isel(file_num=index)
            # Collapse everything but the snapshot axis, so one finite cell anywhere counts.
            present = series.notnull().any(
                dim=[dim for dim in series.dims if dim != axis]
            ).values

            if not present.any():
                continue

            last = present.nonzero()[0][-1]
            # A ragged time has one row per run; a shared one is the same for all of them.
            row = marks[index] if marks.ndim > 1 else marks
            found[int(run)] = float(row[last])

        return found


class _CompatUnpickler(pickle.Unpickler):
    """Unpickle a records.pkl written under a different Python than the one reading it.

    Omphalos runs sweeps in its own environment and the notebooks run in a plotting one, and the two
    are not on the same Python. A pickled `Path` records its class as `pathlib._local.Path` from
    3.13 and as `pathlib.Path` before that, so a records.pkl written by the newer one is unreadable
    from the older with `ModuleNotFoundError: No module named 'pathlib._local'`. Only the module
    name is redirected; the object that comes back is the same.
    """

    def find_class(self, module, name):
        if module == 'pathlib._local':
            module = 'pathlib'

        return super().find_class(module, name)


def _deck_tokens(record):
    """Every value token in one MIN3P deck, as {(block, keyword, line, token): text}."""
    found = {}

    for name, block in record.keyword_blocks.items():
        for keyword, lines in block.contents.items():
            for line_index, line in enumerate(lines):
                for token_index, token in enumerate(line.tokens):
                    found[(name, keyword, line_index, token_index)] = token

    return found


def _number(token):
    """A deck token as a float where it is one, and unchanged where it is not."""
    try:
        return float(token)
    except (TypeError, ValueError):
        return token


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
        source = sweep._completeness_source()
        # Only say 'time' where the numbers are times. MIN3P's spatial output is indexed by a bare
        # snapshot counter, and calling that a time would invite it to be checked against the deck.
        physical = source is None or source[3]
        measure = 'time' if physical else f'{source[1]} index'

        if short:
            write(f'  INCOMPLETE: {len(short)} of {len(completeness)} runs stopped before '
                  f'{furthest:g}, the furthest any run reached')
            for run in short:
                write(f'      run {run}: stopped at {reached[run]:g}')
        elif physical:
            write(f'  all runs reached {furthest:g} '
                  f'-- check that against the time the deck asked for')
        else:
            write(f'  all runs wrote {furthest + 1:g} snapshots (no simulated time recorded '
                  f'against them, only a {measure})')

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
    elif sweep.conditions_path is None and sweep.records_path is None:
        write('  no conditions.nc or records.pkl alongside, so runs cannot be labelled by '
              'what varied')
    elif sweep.conditions_path is None:
        write('  records.pkl records no token that differs between runs')
    else:
        write('  conditions.nc records no parameter that differs between runs')

    write('  groups:')
    for name in sorted(sweep.groups):
        data = sweep.data(name)
        shape = ', '.join(f'{dim}={size}' for dim, size in data.sizes.items())
        variables = list(data.data_vars)
        listed = ', '.join(variables[:4]) + (', ...' if len(variables) > 4 else '')
        write(f'      {name} ({shape}): {len(variables)} variables [{listed}]')
