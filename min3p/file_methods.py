"""File I/O methods for MIN3P.

Re-exports the simulator-agnostic helpers from ``core.file_methods`` and adds
MIN3P-specific TecPlot output parsing. MIN3P output differs from CrunchTope in
two ways that make a dedicated parser necessary:

1. The output *category* is the file **extension** (``.gsp`` spatial profile,
   ``.gst`` transient, ``.gsc``, ``.gsm`` ...) and the timestep index is a
   ``_N`` suffix, so files are named ``{run_name}_{N}.{ext}`` -- whereas
   CrunchTope encodes the category in the filename stem (``totcon1.tec``).
2. Headers are lowercase (``title =`` / ``variables =`` / ``zone t =``) and the
   variable list is comma-separated with inconsistent spacing
   (``"z","h+1"``), rather than uppercase and whitespace-separated.

Verified against ``reactran/MCD-2/min3p/test_*.gsp``.
"""

import glob
import re
from pathlib import Path

import pandas as pd

# Re-export shared helpers for import compatibility with the other backends.
from core.file_methods import (  # noqa: F401
    search_file,
    pickle_data_set,
    unpickle,
)

# Field-output categories in TecPlot format, in three families distinguished by
# their leading column. The full set is transcribed from the MIN3P User Manual
# Tables 2.3-2.6; not every category appears in a given run (``data_cats`` only
# reports those actually written).
#
# SPATIAL 'gs*' + 'vel' -- contour data, leading columns x,(y),(z); one file per
# output time, 'run_N.ext' (N = output-time index). (Manual Tables 2.3 & 2.4.)
SPATIAL_EXTENSIONS = (
    'gsp',   # flow: hydraulic/pressure head, water/gas saturations (Table 2.3)
    'vel',   # interfacial Darcy velocity vx,(vy),(vz) (Table 2.3; own grid)
    'gst',   # total aqueous component concentrations
    'gsc',   # aqueous species concentrations
    'gsi',   # intra-aqueous kinetic reaction rates
    'gsm',   # master variables (pH, pe, Eh, ionic strength, alkalinity, T)
    'gsg',   # partial gas pressures
    'gsgr',  # degassing rates
    'gsv',   # mineral volume fractions (+ porosity)
    'gsb',   # sorbed / surface species
    'gss',   # mineral saturation indices
    'gsd',   # mineral dissolution-precipitation rates
    'gsx',   # excluded-mineral saturation indices
    'gsac',  # activity coefficients
    'gsis',  # isotopes
)
#
# BREAKTHROUGH 'gb*' -- transient data at observation points, leading column
# 'time' (or 'pH' for pC-pH runs); 'run_N.ext' (N = observation-point index).
# (Manual Table 2.5.)
BREAKTHROUGH_EXTENSIONS = (
    'gbt', 'gbc', 'gbi', 'gbm', 'gbg', 'gbgr', 'gbv', 'gbb', 'gbs', 'gbd',
    'gbx', 'gbis', 'gbac',
)
#
# LOCAL BATCH 'lb*' -- local-geochemistry transient / pC-pH data, leading column
# 'time' (or 'pH'); 'run_N.ext' (N = zone index). (Manual Table 2.6.)
BATCH_EXTENSIONS = (
    'lbt', 'lbc', 'lbi', 'lbm', 'lbg', 'lbgr', 'lbv', 'lbb', 'lbs', 'lbd',
    'lbx', 'lbac',
)
#
# All parsed field-output categories.
#
# Deliberately NOT parsed (they are per-domain / per-component / per-mineral
# diagnostics or summaries, not spatial/temporal field data):
#   - flow mass balance:   '_o.mvs', '_o.mvc', '_o.mve' (Table 2.3)
#   - RT mass balance:     '.mac'/'.mae'/'.mmc', '_o.mas'/'.mms'/'.mgs'/'.mss'
#   - charge / mass flux:  '.cbt', '.gmf'
#   - energy balance:      '_o.ebal'/'.ebalc'/'.ebale';  evaporation '.evap'
#   - two-index per-species flux detail '.gsa' ('run_N_M.gsa')
#   - '_o.*' run summaries
OUTPUT_EXTENSIONS = SPATIAL_EXTENSIONS + BREAKTHROUGH_EXTENSIONS + BATCH_EXTENSIONS


def _read_run_name(path):
    """Return the MIN3P run name recorded in ``root.dat`` within ``path``.

    Args:
        path: Directory expected to contain ``root.dat``.

    Returns:
        The run-name token (e.g. ``'test'``), or ``None`` if ``root.dat`` is
        absent or empty.
    """
    root = Path(path) / 'root.dat'
    if not root.is_file():
        return None
    text = root.read_text(errors='replace').strip()
    return text.split()[0] if text else None


def _parse_variables(header_line):
    """Extract column names from a MIN3P ``variables = ...`` header line.

    Args:
        header_line: The second line of a TecPlot file.

    Returns:
        List of column-name strings.
    """
    # Strip the 'variables =' prefix (case-insensitive) and surrounding space.
    body = re.sub(r'^\s*variables\s*=\s*', '', header_line, flags=re.IGNORECASE)
    body = body.strip().strip('"').strip()
    # Split on quote-comma-quote with arbitrary surrounding whitespace.
    return [name.strip().strip('"') for name in re.split(r'"\s*,\s*"', body)]


def parse_output(path, category, time_ref, run_name=None):
    """Parse a MIN3P TecPlot output file at a given timestep into an xarray Dataset.

    Args:
        path: Directory containing the output files.
        category: Output file extension without the dot (e.g. ``'gsp'``).
        time_ref: Timestep index ``N`` in the ``{run_name}_{N}.{ext}`` name.
        run_name: MIN3P run name; read from ``root.dat`` if not supplied.

    Returns:
        xarray Dataset indexed by the spatial coordinates present (X and,
        where the grid is multi-dimensional, Y/Z).

    Raises:
        FileNotFoundError: If the expected output file does not exist.
    """
    if run_name is None:
        run_name = _read_run_name(path)
    if run_name is None:
        raise FileNotFoundError(f"No root.dat found in {path} to determine run name.")

    file_name = Path(path) / f'{run_name}_{time_ref}.{category}'
    if not file_name.is_file():
        raise FileNotFoundError(str(file_name))

    with open(file_name, errors='replace') as f:
        f.readline()                       # line 1: title = "..."
        headers = _parse_variables(f.readline())   # line 2: variables = ...

    df = pd.read_table(
        file_name,
        sep=r'\s+',
        skipinitialspace=True,
        skiprows=[0, 1, 2],                # title, variables, zone
        names=headers,
    )
    ds = df.to_xarray()

    # Coerce any object columns to float (mirrors the CrunchTope parser's guard
    # against mangled small-magnitude scientific notation).
    for variable in ds:
        if ds[variable].dtype == object:
            ds[variable] = (
                ds[variable].astype(str)
                .str.replace(r'\d\.\d+-\d+', '0', regex=True)
                .astype(float)
            )

    # Index the dataset by its natural coordinate. Spatial outputs carry
    # lowercase x/y/z columns; batch/breakthrough outputs carry a single 'time'
    # column -- or, for pC-pH-diagram runs, a 'pH' column (User Manual: "time or
    # pH"). Anything else is left row-indexed.
    coords = [c for c in ('x', 'y', 'z') if c in ds]
    if coords:
        ds = ds.set_index(index=tuple(coords))
        ds = ds.unstack('index')
    else:
        axis = next((c for c in ds if str(c).lower() in ('time', 'ph')), None)
        if axis is not None:
            ds = ds.set_index(index=axis).rename(index=axis)

    return ds


# Extensions never worth copying beside a deck: MIN3P's own field output, the diagnostics and run
# summaries listed above, and the plotting artefacts the benchmarks ship. Everything else sharing the
# deck's stem is treated as an input, so a keyword this version has never heard of still gets its
# file -- the failure that matters is a missing input, and a spare copied file costs nothing.
NON_INPUT_EXTENSIONS = frozenset(OUTPUT_EXTENSIONS) | frozenset({
    # Diagnostics and run summaries.
    'mvs', 'mvc', 'mve', 'mac', 'mae', 'mmc', 'mas', 'mms', 'mgs', 'mss', 'cbt', 'gmf',
    'ebal', 'ebalc', 'ebale', 'evap', 'gsa',
    # Written by the run itself.
    'log', 'fls', 'gen', 'psp', 'cnv', 'tmp', 'tmp1', 'tmp2',
    # Plotting and documentation.
    'lay', 'png', 'wmf', 'tif', 'jpg', 'pdf', 'eps', 'ps', 'xlsx', 'csv', 'pvsm', 'bat', 'html',
})

# The one auxiliary file MIN3P names in the deck rather than after the run.
NAMED_AUXILIARY_FILES = ('solver.cfg',)


def auxiliary_files(template):
    """Return the auxiliary input files a MIN3P deck reads from its working directory.

    MIN3P takes its run name from ``root.dat`` and reads every auxiliary input as
    ``<run name>.<ext>``, so a deck never says what it reads -- it says only that it does.
    ``'read hydraulic conductivity field from file'`` means ``<stem>.hyc``, ``'read initial
    condition from file'`` means ``<stem>.ivs``, ``'transient boundary conditions'`` means
    ``<stem>.bcvs``, and so on through the porosity, CEC, Skempton, specific-storage, energy-balance,
    mineral, unstructured-grid and atmospheric variants. Withholding one is fatal: MIN3P stops with
    ``file <name> missing``.

    Selected by that naming convention rather than by a list of extensions, so a keyword added to a
    later MIN3P still gets its file. Output is excluded by the same convention from the other side:
    it carries an index (``<stem>_12.gsc``) and so never matches ``<stem>.<ext>``.

    Args:
        template: Path to the deck.

    Returns:
        Sorted list of Paths beside the deck, excluding the deck itself.
    """
    template = Path(template)
    directory = template.parent
    stem = template.stem.lower()

    found = [
        path for path in directory.iterdir()
        if path.is_file()
        and path != template
        and path.name.lower() == f'{stem}{path.suffix.lower()}'
        and path.suffix
        # The benchmarks are full of editor backups -- clement.dat~, stedvs.usg~ -- which share the
        # stem and would otherwise be copied into every run directory.
        and not path.name.endswith('~')
        and path.suffix.lstrip('.').lower() not in NON_INPUT_EXTENSIONS
    ]

    found.extend(
        directory / name for name in NAMED_AUXILIARY_FILES if (directory / name).is_file()
    )

    return sorted(found)


def copy_auxiliary_files(template, directory):
    """Copy a deck's auxiliary input files into directory, and return what was copied.

    The MIN3P counterpart of ``omphalos.run._print_aux_files``: a run directory holding only the deck
    can run only those problems that read nothing besides it.
    """
    import shutil

    copied = []

    for path in auxiliary_files(template):
        shutil.copy(path, Path(directory) / path.name)
        copied.append(path.name)

    return copied


def data_cats(path, run_name=None):
    """Return the set of field-output categories (extensions) present in ``path``.

    Only extensions in :data:`OUTPUT_EXTENSIONS` (spatial ``.gsp`` and batch
    ``.lb*`` families) are reported, since those are the field outputs the
    results pipeline concatenates.

    Args:
        path: Directory containing output files.
        run_name: MIN3P run name; read from ``root.dat`` if not supplied.

    Returns:
        Set of category strings (extensions without the dot).
    """
    if run_name is None:
        run_name = _read_run_name(path)
    if run_name is None:
        return set()

    found = set()
    for ext in OUTPUT_EXTENSIONS:
        if glob.glob(str(Path(path) / f'{run_name}_*.{ext}')):
            found.add(ext)
    return found
