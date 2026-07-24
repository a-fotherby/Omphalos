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

Verified against ``reactran/MCD-2/min3p/test_*.gsp``. See
``MIN3P_integration_notes.md`` section 3.
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

# Output extensions that carry field data in TecPlot format, in three families
# distinguished by their leading column. Verified against reactran/MCD-2,
# reactran/dissol, and a live batch/appelo run.
#
# SPATIAL 'gs*' + 'vel' (leading columns x,y,z; one file per output time,
# named 'run_N.ext', N = output-time index):
#   .gsp physical/flow vars (h_w, ph_w, saturation)   .gsc component concs
#   .gsm master vars (pH, ionic strength, alkalinity)  .gst total aqueous concs
#   .gsv mineral volume fractions + porosity           .gss mineral sat. indices
#   .gsd dissolution-precipitation rates               .gsx excluded-mineral SI
#   .vel Darcy velocity (vx,vy,vz) on cell faces (own grid -> own netCDF group)
SPATIAL_EXTENSIONS = ('gsp', 'gsc', 'gsm', 'gst', 'gsv', 'gss', 'gsd', 'gsx', 'vel')
#
# BREAKTHROUGH 'gb*' (leading column 'time'; one file per observation point,
# named 'run_N.ext', N = observation-point index) -- time series at fixed cells:
#   .gbc concs  .gbm master  .gbt totals  .gbv volumes  .gbs SI  .gbd rates  .gbx
BREAKTHROUGH_EXTENSIONS = ('gbc', 'gbm', 'gbt', 'gbv', 'gbs', 'gbd', 'gbx')
#
# LOCAL BATCH 'lb*' (leading column 'time'; one file per zone, N = zone index):
BATCH_EXTENSIONS = ('lbc', 'lbm', 'lbt', 'lbv', 'lbd', 'lbs', 'lbx')
#
# All parsed field-output categories. (Not parsed, by design: per-component /
# per-mineral mass-balance diagnostics '.mac'/'.mae'/'.mmc', the two-index
# per-species flux detail '.gsa' named 'run_N_M.gsa', and the '_o.*' run
# summaries -- these use component/mineral indexing rather than space or time.)
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
    # lowercase x/y/z columns; batch outputs carry a single 'time' column
    # (a time series at one point). Anything else is left row-indexed.
    coords = [c for c in ('x', 'y', 'z') if c in ds]
    if coords:
        ds = ds.set_index(index=tuple(coords))
        ds = ds.unstack('index')
    elif 'time' in ds:
        ds = ds.set_index(index='time').rename(index='time')

    return ds


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
