"""Recompute a CrunchTope database's log K columns with pyGCC, and nothing else.

The existing database stays the authority for everything except the log Ks: which reactions exist,
their stoichiometry, molar volumes, Debye-Huckel sizes, charges, weights, the mineral kinetics block
and the exchange block. pyGCC is asked only for the log K vector of each reaction already listed, at
the desired temperature and pressure, and those columns are written back through the same
(line, token) index database.py builds. Everything else stays byte-identical.

This is deliberately not a database generator. A full pyGCC regeneration produces a different
species set and a uniform placeholder kinetics block -- ``type = tst``, ``rate(25C) = -6.00``,
``activation = 15.0`` for *every* mineral -- so it would discard exactly the fitted values, exchange
coefficients and real kinetic rates, that pyGCC cannot compute. It also needs a CrunchTope writer
that is still not in the public pyGCC release. Updating the log K columns in place keeps the working
database intact and makes temperature and pressure clean sweep axes.

Four things decide whether the result is trustworthy, and all four are enforced here:

* **Reaction matching.** Names differ between compilations, so an alias map is accepted and every
  unmatched reaction is counted and named. ``on_unmatched='error'`` is available for work that
  cannot tolerate a partial update; nothing is ever left stale in silence.
* **Stoichiometry.** A log K belongs to a reaction *as written*. Where the target writes a reaction
  in the opposite direction or scaled by a factor, the value is converted; anything less tractable
  is skipped and reported rather than guessed at.
* **The temperature grid.** The target's own 'temperature points' row is what pyGCC is asked for, so
  the returned vector lines up with the header.
* **Method choices.** ``Dielec_method``, ``heatcap_method`` and ``densityextrap`` all move log K, so
  they are recorded on the result for a caller to store alongside T and P.

Requires ``pygcc >= 1.5.3``: earlier releases return length-1 arrays from ``fsolve`` and
``iapws95(...).rho`` where a scalar is wanted, which is a hard error on NumPy 2.
"""

import math
import re
import warnings

from omphalos.database import HEADER_LINES, tokenise
from omphalos.isotopes import suspected_isotope_pairs

# The Omphalos database sections pyGCC can speak for, mapped to its Specie_class. Surface
# complexation constants are not in a thermodynamic compilation, and exchange coefficients are
# fitted rather than computed, so neither is offered here.
SECTION_SPECIE_CLASS = {
    'minerals': 'minerals',
    'secondary_species': 'aqueous',
    'gases': 'gases',
}

MINIMUM_PYGCC = (1, 5, 3)

UNMATCHED_POLICIES = ('warn', 'error', 'leave')

# Decimal places to write a computed log K to. Both the databases CrunchTope ships and pyGCC's own
# writers use four ('%9.4f' throughout write_database), so this keeps the recomputed columns the
# same width as the ones they replace -- and full float repr would claim a precision the underlying
# SUPCRT fit does not have.
LOG_K_DECIMALS = 4

# What to write where pyGCC cannot compute a value. Its Born functions fail below about
# 350 kg/m3 -- wherever the water is steam rather than liquid -- and it returns NaN there. 500 is
# the sentinel the CrunchTope databases already use for a point with no data; it appears throughout
# the surface complexation and mineral rows as shipped, and pyGCC's own writers substitute exactly
# this ('np.where(np.isnan(logK), 500, logK)'). Writing the NaN through would put the literal text
# 'nan' in the file, which CrunchTope cannot read.
NO_DATA = 500.0

# Every section whose rows carry one log K per temperature point, and so whose every row has to be
# rewritten when the grid changes. These are exactly the four database.F90 reads an ntemp-long
# array for; the exchange block carries a single log K and the kinetics blocks carry none.
GRIDDED_SECTIONS = ('secondary_species', 'gases', 'minerals', 'surface_complexation')

# CrunchTope dimensions its temperature arrays at compile time -- 'INTEGER, PARAMETER :: ntmp=8' in
# params.F90 -- and database.F90 stops outright above it: 'too many temperature points in
# database!'. Going higher needs CrunchTope itself rebuilt.
MAX_TEMPERATURE_POINTS = 8

# CrunchTope fits log K against temperature with five basis functions (nbasis = 5, database.F90),
# so five points is the fewest that determines the fit. One point is a separate, supported case:
# ntemp == 1 is branched out as isothermal and the log K is used directly, no fit involved.
FITTED_TEMPERATURE_POINTS = 5

# How each log K column is written when a row is rebuilt: four decimals, in a column wide enough
# for the sentinel and a sign.
COLUMN_WIDTH = 11


def check_pygcc_version():
    """Fail early if pyGCC is too old to run on NumPy 2.

    Raises:
        ImportError: If pygcc is absent or older than 1.5.3.
    """
    try:
        import importlib.metadata as metadata

        version = metadata.version('pygcc')
    except ImportError as error:
        raise ImportError(
            'Recomputing log K columns needs pygcc >= 1.5.3. Install it with '
            "'pip install \"pygcc>=1.5.3\"'."
        ) from error

    numbers = tuple(int(part) for part in version.split('.')[:3] if part.isdigit())

    if numbers < MINIMUM_PYGCC:
        raise ImportError(
            f'pygcc {version} is installed, but >= 1.5.3 is needed: the three scalar-assignment '
            f'fixes that let it run on NumPy 2 first appear in that release.'
        )

    return version


def signed_stoichiometry(reaction, species_name):
    """Return a reaction as {species: signed coefficient}, the species itself excluded.

    Products are positive and reactants negative, which is the sign convention the database is
    written in. The species being formed carries a coefficient of 1 on the reactant side in both the
    target and the source, and says nothing about how the reaction is scaled, so it is left out of
    the comparison.
    """
    signed = {name: coefficient for name, coefficient in reaction.products.items()}

    for name, coefficient in reaction.reactants.items():
        if name == species_name:
            continue
        signed[name] = signed.get(name, 0.0) - coefficient

    return signed


def stoichiometry_factor(target, source, species_name, tolerance=1e-6):
    """Return the factor the source log K must be multiplied by to suit the target, or None.

    A log K belongs to a reaction as written, so a source reaction written in the opposite direction
    (factor -1) or scaled by some multiple (factor n) needs converting before its value can be used.
    Anything else -- a different basis, a different species set -- is not a rescaling of the same
    reaction and the caller is expected to skip it.

    Args:
        target: The Reaction as the database being edited writes it.
        source: The Reaction as the source compilation writes it.
        species_name: The species both reactions form.
        tolerance: Relative agreement required between the per-species ratios.

    Returns:
        The multiplier, or None where the two are not the same reaction rescaled.
    """
    target_signed = signed_stoichiometry(target, species_name)
    source_signed = signed_stoichiometry(source, species_name)

    if set(target_signed) != set(source_signed):
        return None

    if not target_signed:
        return None

    factors = []

    for name, target_coefficient in target_signed.items():
        source_coefficient = source_signed[name]

        if source_coefficient == 0:
            return None

        factors.append(target_coefficient / source_coefficient)

    first = factors[0]

    if any(abs(factor - first) > tolerance * max(1.0, abs(first)) for factor in factors):
        return None

    return first


def resample(temperatures, source_temperatures, source_values):
    """Put a tabulated vector onto a different temperature grid.

    Points carrying the no-data sentinel are dropped before interpolating rather than treated as
    values -- 500 is not a log K, and interpolating through one would poison its neighbours -- and
    are restored wherever too little is left to interpolate from.

    Interpolation is shape-preserving (PCHIP), which matters because log K curves are monotone over
    most of their range and a natural spline would overshoot near the gaps the sentinels leave.
    Outside the range of real points the nearest end value is held rather than extrapolated: a
    SUPCRT fit says nothing about temperatures it was never given.

    Args:
        temperatures: The grid to resample onto.
        source_temperatures: The grid the values are tabulated on.
        source_values: The values, sentinels included.

    Returns:
        A (values, clamped) pair, where clamped counts the requested temperatures that fell outside
        the range of real source points.
    """
    import numpy as np

    wanted = np.asarray(temperatures, dtype=float)
    known = [
        (temperature, value)
        for temperature, value in zip(source_temperatures, source_values)
        if not math.isnan(value) and value != NO_DATA
    ]

    if len(known) < 2:
        # Nothing to interpolate from. One real point is a constant; none is all sentinel.
        only = known[0][1] if known else NO_DATA
        return [only] * len(wanted), 0

    grid = np.array([point[0] for point in known], dtype=float)
    values_known = np.array([point[1] for point in known], dtype=float)
    order = np.argsort(grid)
    grid, values_known = grid[order], values_known[order]

    clamped = int(np.count_nonzero((wanted < grid[0]) | (wanted > grid[-1])))
    inside = np.clip(wanted, grid[0], grid[-1])

    if len(grid) == 2:
        resampled = np.interp(inside, grid, values_known)
    else:
        from scipy.interpolate import PchipInterpolator

        resampled = PchipInterpolator(grid, values_known)(inside)

    return [float(value) for value in resampled], clamped


class LogKRegrid:
    """The outcome of moving a database onto a different temperature grid."""

    def __init__(self, temperatures, settings):
        self.temperatures = list(temperatures)
        self.settings = settings
        self.recomputed = []
        self.resampled = []
        self.clamped = {}
        self.no_data = {}
        self.isotopes_restored = {}
        self.split_copies = {}

    @property
    def counts(self):
        return {
            'points': len(self.temperatures),
            'recomputed': len(self.recomputed),
            'resampled': len(self.resampled),
            'clamped': len(self.clamped),
            'no_data': len(self.no_data),
        }

    def summary(self):
        lines = [
            f'log K regrid onto {self.temperatures}: {self.counts}',
            f'  settings: {self.settings}',
        ]

        if self.resampled:
            lines.append(
                f'  {len(self.resampled)} row(s) had no computed value and were resampled from '
                f'their own tabulated curve'
            )
        if self.clamped:
            lines.append(
                f'  {len(self.clamped)} resampled row(s) were asked for a temperature outside '
                f'their tabulated range and hold the nearest value there'
            )
        if self.no_data:
            points = sum(self.no_data.values())
            lines.append(
                f'  {points} point(s) across {len(self.no_data)} row(s) written as {NO_DATA:g}'
            )

        if self.isotopes_restored:
            lines.append(
                f'  {len(self.isotopes_restored)} isotopologue row(s) copied back from their '
                f'parents, which were recomputed where the copies could not be'
            )

        return '\n'.join(lines)


class LogKRecalculation:
    """The outcome of a recomputation, as a record of what was done to what."""

    def __init__(self, settings):
        self.settings = settings
        self.updated = {}
        self.unmatched = []
        self.rescaled = {}
        self.skipped = {}
        self.no_data = {}
        # {isotopologue: parent} for copies whose columns this recomputation had separated from
        # their parent's, and which were copied back. pyGCC has no isotopologues, so it moves one
        # side of every such pair and not the other.
        self.isotopes_restored = {}
        # Groups this recomputation split that do NOT look like labelled pairs.
        # Reported, never edited: two rows may share a column without being
        # copies of each other.
        self.split_copies = {}

    @property
    def counts(self):
        return {
            'updated': len(self.updated),
            'unmatched': len(self.unmatched),
            'rescaled': len(self.rescaled),
            'skipped': len(self.skipped),
            'no_data': len(self.no_data),
        }

    def summary(self):
        lines = [f'log K recomputation: {self.counts}', f'  settings: {self.settings}']

        if self.no_data:
            points = sum(self.no_data.values())
            lines.append(
                f'  {points} point(s) across {len(self.no_data)} reaction(s) could not be '
                f'computed and were written as {NO_DATA:g}: {sorted(self.no_data)[:10]}'
            )

        if self.isotopes_restored:
            lines.append(
                f'  {len(self.isotopes_restored)} isotopologue row(s) copied back from the '
                f'parent pyGCC recomputed and they cannot be, so no fractionation is invented: '
                f'{sorted(self.isotopes_restored)[:10]}'
            )

        if self.split_copies:
            lines.append(
                f'  WARNING: {len(self.split_copies)} row(s) were identical to a recomputed row '
                f'before this call and are not now, and their names do not look like an isotope '
                f'label, so they were left alone. Check whether they should have moved together: '
                f'{sorted(self.split_copies)[:10]}'
            )

        if self.rescaled:
            lines.append(f'  rescaled to the target basis: {self.rescaled}')
        if self.unmatched:
            lines.append(f'  not found in the source compilation: {sorted(self.unmatched)}')
        for name, reason in sorted(self.skipped.items()):
            lines.append(f'  skipped {name}: {reason}')

        return '\n'.join(lines)


class Augmentation:
    """What adding species from a source compilation did, and what it could not do."""

    def __init__(self, settings):
        self.settings = settings
        self.added = {}
        self.already_present = []
        self.unknown = []
        self.unsupported = {}
        self.no_data = {}

    @property
    def counts(self):
        return {
            'added': sum(len(names) for names in self.added.values()),
            'already_present': len(self.already_present),
            'unknown': len(self.unknown),
            'unsupported': len(self.unsupported),
        }

    def summary(self):
        lines = [f'database augmentation: {self.counts}', f'  settings: {self.settings}']

        for section, names in sorted(self.added.items()):
            lines.append(f'  {section}: {len(names)} added, {names[:8]}')

        if self.already_present:
            lines.append(f'  already in the database, left alone: {sorted(self.already_present)}')

        if self.unknown:
            lines.append(
                f'  not in the source compilation: {sorted(self.unknown)}'
            )

        for name, reason in sorted(self.unsupported.items()):
            lines.append(f'  skipped {name}: {reason}')

        if self.no_data:
            points = sum(self.no_data.values())
            lines.append(
                f'  {points} point(s) across {len(self.no_data)} row(s) written as {NO_DATA:g}'
            )

        return '\n'.join(lines)


def in_any_section(database, name):
    """Whether the database holds this species anywhere a reaction may stand on it."""
    return any(
        name in getattr(database, section, {})
        for section in ('primary_species', 'secondary_species', 'gases', 'minerals')
    )


def database_newline():
    """CrunchTope databases are CRLF; a row appended with a bare newline breaks the file."""
    return '\r\n'


class LogKCalculator:
    """Asks pyGCC for the log K of reactions a CrunchTope database already lists."""

    def __init__(self, sourcedb='thermo.2021', sourceformat='GWB', Dielec_method='JN91',
                 heatcap_method='SUPCRT', densityextrap=False, aliases=None, pressure=None):
        """
        Args:
            sourcedb: The source thermodynamic compilation, as pyGCC names it.
            sourceformat: Its format: 'GWB', 'EQ36', 'PHREEQC', 'Pflotran' or 'ToughReact'.
            Dielec_method: 'JN91', 'FGL97' or 'DEW'.
            heatcap_method: 'SUPCRT', 'Berman88', 'HP11' or 'HF76'.
            densityextrap: Whether to extrapolate below 350 kg/m3.
            aliases: {database name: source name}, for reactions the two compilations spell
                differently.
            pressure: The pressure to compute at, in bar. None keeps the water saturation curve,
                which is how a .dbs is conventionally tabulated. A number applies that pressure at
                every temperature point; a sequence gives one pressure per point.

                A CrunchTope database has no pressure row -- its header carries only the
                temperature points and the Debye-Huckel coefficients -- so a database recomputed at
                depth looks no different from one at saturation, and carries no record of which it
                is. Record the pressure with the run.
        """
        self.version = check_pygcc_version()

        from pygcc.pygcc_utils import db_reader

        self.sourcedb = sourcedb
        self.sourceformat = sourceformat
        self.Dielec_method = Dielec_method
        self.heatcap_method = heatcap_method
        self.densityextrap = densityextrap
        self.aliases = dict(aliases or {})
        self.pressure = pressure
        self.cache = {}
        self.water = {}

        self.source = db_reader(sourcedb=sourcedb, sourceformat=sourceformat)

    @property
    def settings(self):
        """The choices that move log K, for recording alongside the results."""
        return {
            'pygcc': self.version,
            'sourcedb': self.sourcedb,
            'sourceformat': self.sourceformat,
            'Dielec_method': self.Dielec_method,
            'heatcap_method': self.heatcap_method,
            'densityextrap': self.densityextrap,
            # 'saturation' rather than None, so a record says what was done rather than what was
            # left unset. The database itself cannot carry this.
            'pressure': 'saturation' if self.pressure is None else self.pressure,
        }

    def pressures(self, temperatures):
        """Return the P argument for pyGCC at the given temperatures.

        Raises:
            ValueError: If a sequence of pressures does not match the temperature grid.
        """
        if self.pressure is None:
            # pyGCC's idiom for the saturation curve.
            return 'T'

        if isinstance(self.pressure, (int, float)):
            return [float(self.pressure)] * len(temperatures)

        values = [float(value) for value in self.pressure]

        if len(values) != len(temperatures):
            raise ValueError(
                f'pressure has {len(values)} values but the database has {len(temperatures)} '
                f'temperature points. Give one pressure per point, a single pressure for all of '
                f'them, or none for the saturation curve.'
            )

        return values

    def source_reaction(self, name):
        """Return the source compilation's reaction for a name, or None.

        The source entry is [formula, count, coefficient, species, ...] -- the same shape as the
        reaction portion of a CrunchTope row, so the same Reaction class reads both.
        """
        from omphalos.database import Reaction

        entry = self.source.sourcedic.get(self.aliases.get(name, name))

        if entry is None:
            return None

        count = int(entry[1])
        array = [
            float(value) if index % 2 == 0 else value
            for index, value in enumerate(entry[2:2 + count * 2])
        ]

        return Reaction(name, array)

    def water_properties(self, temperatures, pressures):
        """Return the resolved pressures and the water properties pyGCC needs on this grid.

        calcRxnlogK recomputes density, dielectric constant and the Gibbs energy of water on every
        call unless they are handed to it, and that is nearly all the cost of a call: pyGCC's own
        writers compute them once and pass them into all 34 of their call sites, which is why
        generating a whole database takes about a second while calling it per reaction takes about
        half a second each. They depend only on the grid, so they are computed once per grid here.

        Returns:
            A (pressures, rhoEG) pair. The pressures are resolved to numbers, so a saturation-curve
            request is not re-derived per reaction either.
        """
        key = (temperatures, pressures)

        if key in self.water:
            return self.water[key]

        import numpy as np

        from pygcc.pygcc_utils import ZhangDuan, iapws95, water_dielec

        temperature = np.asarray(temperatures, dtype=float)

        if pressures == 'T':
            # pyGCC's own idiom for the saturation curve, resolved here rather than per call.
            pressure = np.asarray(iapws95(T=temperature, P='T').P, dtype=float)
        else:
            pressure = np.asarray(pressures, dtype=float)

        water = (ZhangDuan(T=temperature, P=pressure)
                 if self.Dielec_method.upper() == 'DEW'
                 else iapws95(T=temperature, P=pressure))

        rhoEG = {
            'rho': water.rho,
            'E': water_dielec(T=temperature, P=pressure,
                              Dielec_method=self.Dielec_method).E,
            'dGH2O': water.G,
        }

        self.water[key] = (pressure, rhoEG)

        return self.water[key]

    def _log_k(self, name, specie_class, temperatures, pressures):
        """Ask pyGCC for one reaction's log K vector.

        Cached on the calculator rather than with lru_cache, which would take `self` as part of the
        key and so hold every calculator ever made, source compilation included, for the life of
        the process. Each call is a SUPCRT-style calculation of order half a second, and a sweep
        would otherwise ask for the same (reaction, grid, pressure) once per run.
        """
        import numpy as np

        from pygcc.pygcc_utils import calcRxnlogK

        cached = self.cache.get((name, specie_class, temperatures, pressures))

        if cached is not None:
            return cached

        if self.densityextrap:
            # Extrapolating below 350 kg/m3 needs a second set of water properties on a grid pyGCC
            # derives per call, so let it build both rather than hand it half of what it needs.
            pressure = 'T' if pressures == 'T' else np.asarray(pressures, dtype=float)
            rhoEG = None
        else:
            pressure, rhoEG = self.water_properties(temperatures, pressures)

        result = calcRxnlogK(
            # An array, not a list: pyGCC does arithmetic on this directly.
            T=np.asarray(temperatures, dtype=float),
            P=pressure,
            rhoEG=rhoEG,
            Specie=name,
            Specie_class=specie_class,
            dbaccessdic=self.source.dbaccessdic,
            sourcedic=self.source.sourcedic,
            specielist=self.source.specielist,
            sourceformat=self.sourceformat,
            Dielec_method=self.Dielec_method,
            heatcap_method=self.heatcap_method,
            densityextrap=self.densityextrap,
        )

        computed = [float(value) for value in result.logK]
        self.cache[(name, specie_class, temperatures, pressures)] = computed

        return computed

    def log_k(self, name, specie_class, temperatures, quiet=False):
        """Return a reaction's log K vector at the given temperatures, or None if pyGCC cannot.

        Args:
            quiet: Suppress the per-reaction warning. Set when the caller has a fallback and is
                counting the failures itself -- asking pyGCC for a whole database means hundreds of
                reactions it holds no data for, and a warning each is noise, not information.
        """
        source_name = self.aliases.get(name, name)
        pressures = self.pressures(temperatures)
        pressures = 'T' if pressures == 'T' else tuple(pressures)

        try:
            return self._log_k(source_name, specie_class, tuple(temperatures), pressures)
        except Exception as error:
            if not quiet:
                warnings.warn(
                    f"pyGCC could not compute log K for '{name}': {type(error).__name__}: {error}"
                )
            return None

    def recompute(self, database, sections=None, reactions='all', on_unmatched='warn'):
        """Rewrite a database's log K columns in place.

        Args:
            database: The Database to edit. Only its log K tokens are touched.
            sections: Which sections to recompute. Defaults to every section pyGCC can speak for.
            reactions: 'all', or a list of names to restrict to.
            on_unmatched: 'warn', 'error' or 'leave'. A reaction the source does not have keeps the
                value it had; this says how loudly to say so.

        Returns:
            A LogKRecalculation recording what was updated, rescaled, skipped and unmatched.

        Raises:
            ValueError: On an unknown section or policy, or, with on_unmatched='error', where any
                reaction could not be matched.
        """
        if on_unmatched not in UNMATCHED_POLICIES:
            raise ValueError(
                f"on_unmatched must be one of {UNMATCHED_POLICIES}, got '{on_unmatched}'."
            )

        sections = list(SECTION_SPECIE_CLASS) if sections is None else list(sections)
        unknown = set(sections) - set(SECTION_SPECIE_CLASS)

        if unknown:
            raise ValueError(
                f'pyGCC cannot compute log K for {sorted(unknown)}. Available: '
                f'{sorted(SECTION_SPECIE_CLASS)}. Exchange coefficients and surface complexation '
                f'constants are fitted, not computed, and are edited directly instead.'
            )

        wanted = None if reactions == 'all' else set(reactions)
        # The target's own grid, so the returned vector lines up with its header.
        temperatures = tuple(float(value) for value in database.temp_field)
        result = LogKRecalculation(self.settings)
        # Taken before anything is rewritten: rows byte-identical now and not afterwards have been
        # split by this call. See rejoin_split_copies.
        before = self.identical_columns(database, sections)

        for section in sections:
            specie_class = SECTION_SPECIE_CLASS[section]

            for name, entry in getattr(database, section).items():
                if wanted is not None and name not in wanted:
                    continue

                source = self.source_reaction(name)

                if source is None:
                    result.unmatched.append(f'{section}/{name}')
                    continue

                factor = stoichiometry_factor(entry.reaction, source, name)

                if factor is None:
                    result.skipped[f'{section}/{name}'] = 'stoichiometry is not a rescaling'
                    continue

                values = self.log_k(name, specie_class, temperatures)

                if values is None:
                    result.skipped[f'{section}/{name}'] = 'pyGCC could not compute it'
                    continue

                if factor != 1.0:
                    values = [factor * value for value in values]
                    result.rescaled[f'{section}/{name}'] = factor

                missing = sum(1 for value in values if math.isnan(value))

                if missing:
                    values = [NO_DATA if math.isnan(value) else value for value in values]
                    result.no_data[f'{section}/{name}'] = missing

                # Written as fixed-point text, so a value that rounds short keeps its trailing
                # zeros and the column stays the width the database had it at.
                database.modify(
                    section, name, 'log_k',
                    [f'{value:.{LOG_K_DECIMALS}f}' for value in values],
                )
                result.updated[f'{section}/{name}'] = [
                    round(value, LOG_K_DECIMALS) for value in values
                ]

        self.rejoin_split_copies(database, before, result)

        self._report(result, on_unmatched)

        return result

    @staticmethod
    def identical_columns(database, sections):
        """Group the names in these sections by the log K column they carry.

        Only groups of more than one are kept. Two rows with byte-identical columns are, in a
        thermodynamic database, one reaction written twice -- which is exactly what an isotopologue
        is, since add_isotope copies the log Ks unchanged rather than offsetting them.
        """
        columns = {}

        for section in sections:
            for name in getattr(database, section, {}):
                try:
                    value = database.value(section, name, 'log_k')
                except KeyError:
                    continue
                if isinstance(value, list):
                    columns.setdefault((section, tuple(value)), []).append(name)

        return {key: names for key, names in columns.items() if len(names) > 1}

    def rejoin_split_copies(self, database, before, result, updated_keys=None):
        """Put back together any group of identical rows this recomputation split.

        pyGCC can compute `H2S(aq)` and has never heard of `H2S34(aq)`: it holds no isotopologues at
        all. So a recomputation moves one side of every labelled pair and leaves the other, and the
        gap that opens between them is an equilibrium fractionation the database never had -- silent,
        and on `SukindaCr53.dbs` at 500 bar as large as 0.33 log units, which is the same order as
        the signal an isotope model exists to measure.

        Detection is mechanical rather than by name: a group whose rows were byte-identical before
        and are not after, where pyGCC updated some members and not others, has been split by this
        call. Names are only used to decide whether it is safe to *act* -- `H2O2` looks exactly like
        a labelled `H2O`, so a name test alone would corrupt a database. A group that splits without
        looking like a labelled pair is reported and left alone.
        """
        # Authoritative where it exists -- add_isotope records what it created, names given by hand
        # included -- and the name heuristic only as a fallback for a database that merely ships with
        # isotopologues.
        declared = getattr(database, 'isotope_pairs', None) or {}
        suspected = dict(suspected_isotope_pairs(database))
        suspected.update({child: parent for parent, child in declared.items()})

        if updated_keys is None:
            # recompute() records what it wrote in `updated`; regrid() rewrites every row and
            # records only which of them pyGCC supplied a value for.
            updated_keys = set(getattr(result, 'updated', None) or getattr(result, 'recomputed', []))

        for (section, _), names in before.items():
            updated = [name for name in names if f'{section}/{name}' in updated_keys]
            left = [name for name in names if f'{section}/{name}' not in updated_keys]

            if not updated or not left:
                continue

            source = updated[0]
            values = database.value(section, source, 'log_k')

            for name in left:
                labelled = suspected.get(name) in names or suspected.get(source) == name
                if labelled:
                    database.modify(section, name, 'log_k',
                                    [f'{float(value):.{LOG_K_DECIMALS}f}' for value in values])
                    result.isotopes_restored[f'{section}/{name}'] = f'{section}/{source}'
                else:
                    result.split_copies[f'{section}/{name}'] = f'{section}/{source}'

    def regrid(self, database, temperatures, reactions='all'):
        """Rewrite a database onto a different set of temperature points.

        A CrunchTope database tabulates every log K at the temperatures its first line names, and
        interpolates between them at run time. A model that lives between 2 and 40 degrees spends
        five of the usual eight points on 100-300, so a grid chosen for the problem is worth having.

        Unlike recompute(), this is not a token edit: changing the number of points changes the
        width of every row that carries a log K vector, so those rows are rebuilt. *Every* row in
        those sections is rewritten, whatever `reactions` says -- a file with rows of two different
        widths is not a database. What `reactions` selects is which rows pyGCC is asked to compute;
        the rest are resampled from the curve they already carry, which is also what happens to any
        reaction pyGCC does not have or writes on an incompatible basis.

        The three Debye-Huckel rows are resampled the same way rather than recomputed. pyGCC's Ah
        and Bh reproduce the shipped values, but its B-dot follows a different correlation, and
        changing a database's activity model is not what regridding it should mean.

        Args:
            database: The Database to rewrite, in place.
            temperatures: The new grid, in degrees Celsius.
            reactions: 'all', or the names to ask pyGCC for.

        Returns:
            A LogKRegrid recording what was computed, what was resampled and where.

        Raises:
            ValueError: If the grid is empty, or has more points than CrunchTope can hold.
        """
        temperatures = [float(value) for value in temperatures]

        if not temperatures:
            raise ValueError('A database needs at least one temperature point.')


        if len(temperatures) > MAX_TEMPERATURE_POINTS:
            raise ValueError(
                f'{len(temperatures)} temperature points, but CrunchTope is built for at most '
                f'{MAX_TEMPERATURE_POINTS} (ntmp in params.F90) and stops with "too many '
                f'temperature points in database!" above that. Rebuild CrunchTope with a larger '
                f'ntmp, or use fewer points.'
            )

        if 1 < len(temperatures) < FITTED_TEMPERATURE_POINTS:
            warnings.warn(
                f'{len(temperatures)} temperature points leaves CrunchTope\'s log K fit '
                f'underdetermined: it uses {FITTED_TEMPERATURE_POINTS} basis functions '
                f'(nbasis in database.F90). Use one point for an isothermal problem, which is '
                f'branched out and needs no fit, or at least {FITTED_TEMPERATURE_POINTS}.'
            )

        wanted = None if reactions == 'all' else set(reactions)
        old_temperatures = [float(value) for value in database.temp_field]
        # Same reason as in recompute(): a labelled pair whose parent pyGCC can compute and whose
        # copy it cannot has one row recomputed and the other resampled, which separates them.
        before = self.identical_columns(database, GRIDDED_SECTIONS)
        result = LogKRegrid(temperatures, self.settings)

        for section in GRIDDED_SECTIONS:
            entries = getattr(database, section)
            specie_class = SECTION_SPECIE_CLASS.get(section)

            for name, entry in entries.items():
                computed = None

                if specie_class is not None and (wanted is None or name in wanted):
                    computed = self.computed_column(name, specie_class, temperatures, entry)

                if computed is None:
                    computed, clamped = resample(
                        temperatures, old_temperatures, entry.log_k
                    )
                    result.resampled.append(f'{section}/{name}')

                    if clamped:
                        result.clamped[f'{section}/{name}'] = clamped
                else:
                    result.recomputed.append(f'{section}/{name}')

                missing = sum(1 for value in computed if math.isnan(value))

                if missing:
                    computed = [NO_DATA if math.isnan(value) else value for value in computed]
                    result.no_data[f'{section}/{name}'] = missing

                self.write_column(database, entry, computed)

        self.write_header(database, temperatures, old_temperatures)
        database.reparse()

        # Same hazard as in recompute(): a labelled pair whose parent pyGCC can compute and whose
        # copy it cannot ends up with one row recomputed and the other resampled.
        self.rejoin_split_copies(database, before, result)

        print(result.summary())

        return result

    def computed_column(self, name, specie_class, temperatures, entry):
        """Return pyGCC's log K for one reaction on the new grid, or None if it cannot supply one."""
        source = self.source_reaction(name)

        if source is None:
            return None

        factor = stoichiometry_factor(entry.reaction, source, name)

        if factor is None:
            return None

        values = self.log_k(name, specie_class, temperatures, quiet=True)

        if values is None:
            return None

        return values if factor == 1.0 else [factor * value for value in values]

    @staticmethod
    def write_column(database, entry, values):
        """Rewrite one row's log K columns, however many there now are."""
        first = entry.parameters['log_k'][1][0]
        last = first + len(entry.log_k)

        database.replace_tokens(
            entry.line_index, first, last,
            [f'{value:>{COLUMN_WIDTH}.{LOG_K_DECIMALS}f}' for value in values],
        )

    # ------------------------------------------------------------------ augmentation

    def source_fields(self, name):
        """Return (charge, ion size, molecular weight, molar volume) from the source compilation.

        A CrunchTope row needs more than a reaction and a log K. pyGCC carries the rest: molecular
        weights in `MWdic`, charge and ion size in `chargedic`, and the molar volume as the sixth
        field of a `dbaccessdic` entry -- the V of the SUPCRT record, which reproduces the shipped
        Calcite volume (36.934) exactly.
        """
        weight = self.source.MWdic.get(name)

        charge, size = None, None
        record = self.source.chargedic.get(name)

        if record:
            numbers = re.findall(r'=\s*(-?[\d.]+)', str(record))
            if len(numbers) >= 2:
                charge, size = float(numbers[0]), float(numbers[1])

        volume = None
        entry = self.source.dbaccessdic.get(name)

        if isinstance(entry, (list, tuple)) and len(entry) > 5:
            try:
                volume = float(entry[5])
            except (TypeError, ValueError):
                volume = None

        return charge, size, weight, volume

    def add_species(self, database, sections, on_unknown='warn'):
        """Add named species from the source compilation to a database that lacks them.

        The alternative to regenerating a database wholesale, which discards exactly the custom
        species, exchange coefficients and fitted rates that make one usable. This adds the row and
        changes nothing else.

        A reaction is only added where every species it stands on is already in the target, since a
        row written on a basis the database does not have is one CrunchTope stops reading. Those are
        reported rather than resolved: pulling dependencies in recursively would grow the database
        in ways the modeller did not ask for.

        Args:
            database: The Database to add to, in place. Rewritten and reparsed.
            sections: {section name: [species names]}, e.g. {'minerals': ['Anhydrite']}.
            on_unknown: 'warn', 'error' or 'leave', for names the compilation does not have.

        Returns:
            An Augmentation.
        """
        result = Augmentation(self.settings)
        temperatures = tuple(float(value) for value in database.temp_field)
        new_rows = {}

        for section, names in (sections or {}).items():
            if section not in GRIDDED_SECTIONS:
                raise ValueError(
                    f"ConfigError: '{section}' cannot be added to. Species with a log K column "
                    f'live in {sorted(GRIDDED_SECTIONS)}.'
                )

            for name in names:
                if name in getattr(database, section, {}):
                    result.already_present.append(name)
                    continue

                reaction = self.source_reaction(name)

                if reaction is None:
                    result.unknown.append(name)
                    continue

                basis = {s for s in reaction.products} | {
                    s for s in reaction.reactants if s != name
                }
                missing = sorted(s for s in basis if not in_any_section(database, s))

                if missing:
                    result.unsupported[name] = (
                        f'written on {missing}, which this database does not have'
                    )
                    continue

                values = self.log_k(name, SECTION_SPECIE_CLASS[section], temperatures)

                if values is None:
                    result.unsupported[name] = 'pyGCC could not compute its log K'
                    continue

                blanks = sum(1 for value in values if math.isnan(value))

                if blanks:
                    values = [NO_DATA if math.isnan(value) else value for value in values]
                    result.no_data[f'{section}/{name}'] = blanks

                line = self.build_row(section, name, reaction, values)

                if line is None:
                    result.unsupported[name] = 'the source compilation gave no molecular weight'
                    continue

                new_rows.setdefault(section, []).append(line)
                result.added.setdefault(section, []).append(name)

        for section, lines in new_rows.items():
            database.insert_lines(database.section_end(section), lines)

        if new_rows:
            database.reparse()

        self._report_unknown(result, on_unknown)

        return result

    def build_row(self, section, name, reaction, values):
        """Write one database row, in the layout its section uses."""
        charge, size, weight, volume = self.source_fields(name)

        if weight is None:
            return None

        signed = dict(reaction.products)
        for species, coefficient in reaction.reactants.items():
            if species != name:
                signed[species] = signed.get(species, 0.0) - coefficient

        stoichiometry = ' '.join(
            f'{coefficient:>9.4f} {chr(39)}{species}{chr(39)}'
            for species, coefficient in signed.items()
        )
        columns = ' '.join(f'{value:>{COLUMN_WIDTH}.{LOG_K_DECIMALS}f}' for value in values)

        if section == 'minerals':
            head = f"'{name}' {volume if volume is not None else 0.0:>9.4f} {len(signed):>3d}"
            tail = f' {weight:>10.4f}'
        elif section == 'gases':
            head = f"'{name}' {volume if volume is not None else 0.0:>9.4f} {len(signed):>3d}"
            tail = f' {weight:>10.4f}'
        else:
            head = f"'{name}' {len(signed):>3d}"
            tail = (f' {size if size is not None else 3.0:>5.1f}'
                    f' {charge if charge is not None else 0.0:>5.1f}'
                    f' {weight:>10.4f}')

        return f'{head}  {stoichiometry}  {columns}{tail}{database_newline()}'

    @staticmethod
    def _report_unknown(result, on_unknown):
        if not result.unknown or on_unknown == 'leave':
            return

        message = (
            f'{len(result.unknown)} species(s) are not in the source compilation and were not '
            f'added: {sorted(result.unknown)}'
        )

        if on_unknown == 'error':
            raise ValueError(message)

        warnings.warn(message)

    @staticmethod
    def write_header(database, temperatures, old_temperatures):
        """Rewrite the temperature row and resample the three Debye-Huckel rows onto it."""
        header = tokenise(database.lines[0])
        database.replace_tokens(
            0, 1, len(header),
            [f'{len(temperatures):>4d}']
            + [f'{value:>{COLUMN_WIDTH}.{LOG_K_DECIMALS}f}' for value in temperatures],
        )

        for line_index in range(1, HEADER_LINES):
            row = tokenise(database.lines[line_index])
            resampled, _ = resample(
                temperatures, old_temperatures, [value for value, _, _ in row[1:]]
            )
            database.replace_tokens(
                line_index, 1, len(row),
                [f'{value:>{COLUMN_WIDTH}.{LOG_K_DECIMALS}f}' for value in resampled],
            )

    @staticmethod
    def _report(result, on_unmatched):
        """Say what was not updated. Never leave a stale log K in silence."""
        if result.no_data:
            points = sum(result.no_data.values())
            warnings.warn(
                f'{points} log K point(s) across {len(result.no_data)} reaction(s) could not be '
                f'computed -- pyGCC returns NaN where the water is not liquid -- and were written '
                f'as {NO_DATA:g}, the no-data value. Check the pressure suits the temperature '
                f'grid: {sorted(result.no_data)[:10]}'
            )

        stale = result.unmatched + sorted(result.skipped)

        if not stale or on_unmatched == 'leave':
            return

        message = (
            f'{len(stale)} reaction(s) kept their existing log K: '
            f'{stale[:20]}{" ..." if len(stale) > 20 else ""}'
        )

        if on_unmatched == 'error':
            raise ValueError(message)

        warnings.warn(message)
