"""Inspect, validate and regrid CrunchTope restart (``.rst``) files.

A CrunchTope restart file is a Fortran *unformatted sequential* dump of the whole solver state --
one record per array -- written by ``CrunchTope.F90`` and read back by ``restart.F90``. The file
stores **no grid dimensions**, so a restart is only valid for a run whose ``xzones`` discretisation
matches the one that wrote it: handing a 350-cell ``.rst`` to a 3500-cell run fails on the first
array read.

This module resamples the file onto a different ``nx``, letting a converged coarse-grid solution
seed a fine-grid run with every field already in the right place -- something a zoned
``INITIAL_CONDITIONS`` block cannot do, because it can only impose piecewise-constant states drawn
from the ``CONDITION`` blocks.

Layout
------
Record *order* and record *shapes* both mirror the writer. The shapes are taken from the ``ALLOCATE``
statements in ``BOGLSource2026`` (see :data:`DECLARATIONS`), written out verbatim so that a future
CrunchTope release can be diffed against them.

A declaration fixes the hard part -- which axis is x, and what the transverse extents are -- while
the x extent itself is solved from the record's actual element count. That tolerates the one kind of
build drift seen in practice, a bound changing between ``nx`` and ``0:nx+1``, and it is why the
element count is checked rather than predicted: a record that cannot be reconciled with its
declaration raises instead of being reshaped on a guess.

Pure factorisation is kept only as a fallback for records with no declaration. It is not reliable on
its own: at ``nx = 10`` it silently prefers ``sp = (3, 10, 4, 4)`` over the true
``(ncomp+nspec, nx+2)``, because a small ``nx`` admits spurious factorisations that a large one does
not.

Padding conventions, for an x bound written ``lo:hi``:

==============  =========  ===  ==========================
bound           extent     pad  meaning
==============  =========  ===  ==========================
``nx``          ``nx``       0  cell centred
``0:nx``        ``nx+1``     1  face centred
``0:nx+1``      ``nx+2``     2  one ghost layer
``-1:nx+1``     ``nx+3``     3
``-1:nx+2``     ``nx+4``     4  two ghost layers
==============  =========  ===  ==========================

Transverse axes carry their own ghosts, so for a 1-D column ``0:ny+1`` stores 3 values of which the
*middle* is physical. Index 0 is a ghost layer, and for ``s`` it is full of zeros.

Restarting: what the file overrides
-----------------------------------
* ``restart.F90`` reads ``time``, ``nn`` and ``nint`` unconditionally, so neither the clock nor the
  tecplot file numbering restarts from zero.
* ``READ(iures) DummyReal,dtold,DummyReal,DummyReal,DummyReal,dtmax`` -- ``dtmax`` comes from the
  file and ``delt``, ``tstep``, ``deltmin`` and ``dtmaxcour`` are discarded. ``timestep_max`` in a
  restarted deck is therefore **silently overridden** by the previous stage's value; use
  ``set_dtmax``. ``dtold`` is likewise restored, against a ``delt`` that restarts from
  ``timestep_init``; ``set_dtold`` rescales it.
* ``CALL restart`` runs *after* ``CALL StartTope``, so anything in the ``.rst`` overrides the deck.
  For porosity that is silent corruption -- a resampled ``por`` supersedes ``read_PorosityFile`` --
  hence ``inject``.
* Use the ``append`` keyword. Without it ``prtint(nint)`` reads past the end of an ``nstop``-long
  array and ``nint >= nstop`` ends the run immediately. Omphalos already emits it.

Consistency
-----------
``sp``, ``sp10``, ``s``, ``sn``, ``spold``, ``spnO2`` and ``spnnO2`` are not independent. Resampling
each separately breaks the relations between them and GIMRT fails Newton on the first step; see
:func:`enforce_consistency`, which :func:`regrid` applies by default.

Verified against ``BOGLSource2026``. The record list and the declarations both couple this module to
that build: an unexpected record count raises rather than mis-parsing, which is the right failure
mode, but a CrunchTope upgrade may need :data:`DECLARATIONS` extended.

Note that ``grep`` treats most ``BOGLSource2026/*.F90`` files as binary -- the copyright headers
contain invalid UTF-8 -- so any source archaeology needs ``grep -a``.

Examples
--------
::

    python -m omphalos.restart_file inspect run.rst --nx 350 --input model.in
    python -m omphalos.restart_file verify  run.rst --nx 350 --input model.in \\
                                            --identity --reference . --invariants
    python -m omphalos.restart_file regrid  run.rst --input model.in \\
                                            --nx-in 350 --nx-out 3500 -o fine.rst
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import struct
import sys
from dataclasses import dataclass, field
from itertools import product
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

MARKER = struct.Struct("<i")
MARKER_SIZE = MARKER.size

#: Largest ghost/face padding considered for an x extent.
MAX_PAD = 6

#: Per-dimension transverse extents a 1-D run can produce.
_TRANSVERSE_DIMS = (1, 2, 3, 4, 5)

#: Products of at most two transverse dimensions.
TRANSVERSE_OK = {a * b for a, b in product(_TRANSVERSE_DIMS, repeat=2)}

# Record order as written by CrunchTope.F90. Two blocks are conditional, so the record count
# identifies which of them fired.
_BASE = """time nn nint tsteps keqaq keqgas keqsurf xgram spnO2 spnnO2 sp s sn
           sp10 spold spex spex10 gam exchangesites spexold spgas spgasold
           spgas10""".split()
_SATURATE = ["sgas", "sgasn"]        # written when isaturate == 1
_ERODE = ["ssurf", "ssurfn"]         # written when ierode == 1
_TAIL = """sexold ssurfold spsurf spsurf10 spsurfold raq_tot sion jinit keqmin
           volfx dppt area LogPotential t told ro por satliq qxgas qygas qzgas
           pres dspy dspz qg ActiveCell VolSaveByTimeStep Volsave
           ncounter""".split()

#: Records holding INTEGER(I4B) rather than REAL(DP).
INT_RECORDS = frozenset({"nn", "nint", "jinit", "ActiveCell", "ncounter"})

#: Scalar/header records copied through untouched.
HEADER_RECORDS = frozenset({"time", "nn", "nint", "tsteps"})

#: Integer fields are labels, not quantities: resample by nearest neighbour.
NEAREST_RECORDS = frozenset({"jinit", "ActiveCell"})

#: Floor applied before taking logs, matching CrunchTope's own concentration floor.
CONC_FLOOR = 1.0e-30

#: Blocks counted in a CrunchTope input deck to fix the leading axis sizes.
_DIM_BLOCKS = ("PRIMARY_SPECIES", "SECONDARY_SPECIES", "AQUEOUS_KINETICS",
               "MINERALS", "GASES", "ION_EXCHANGE", "SURFACE_COMPLEXATION")

#: Input-deck block that determines each Fortran dimension symbol. Symbols with no entry here
#: (``nsurf_sec``, ``nexch_sec``, ``nreactmax``) are database-derived and so left free, to be
#: solved from the record's element count.
_SYMBOL_BLOCKS = {
    "ncomp": "PRIMARY_SPECIES",
    "nspec": "SECONDARY_SPECIES",
    "ngas": "GASES",
    "nrct": "MINERALS",
    "ikin": "AQUEOUS_KINETICS",
    "nexchange": "ION_EXCHANGE",
    "nsurf": "SURFACE_COMPLEXATION",
}

#: Array declarations, copied verbatim from the ``ALLOCATE`` statements in BOGLSource2026. Several
#: arrays are allocated differently depending on which transverse axes are ghosted; every variant is
#: listed and the one matching the record's element count is chosen. Records absent from this table
#: fall back to factorisation.
DECLARATIONS = {
    "keqaq": ["keqaq(nspec,nx,ny,nz)"],
    "keqgas": ["keqgas(ngas,nx,ny,nz)"],
    "keqsurf": ["keqsurf(nsurf_sec,nx,ny,nz)"],
    "xgram": ["xgram(-1:nx+1,0:ny+1,0:nz+1)"],
    "spnO2": ["spnO2(nx,ny,nz)"],
    "spnnO2": ["spnnO2(nx,ny,nz)"],
    "sp": ["sp(ncomp+nspec,0:nx+1,ny,nz)",
           "sp(ncomp+nspec,0:nx+1,0:ny+1,nz)",
           "sp(ncomp+nspec,0:nx+1,ny,0:nz+1)",
           "sp(ncomp+nspec,0:nx+1,0:ny+1,0:nz+1)"],
    "s": ["s(ncomp,0:nx+1,0:ny+1,nz)",
          "s(ncomp,0:nx+1,ny,0:nz+1)",
          "s(ncomp,0:nx+1,0:ny+1,0:nz+1)"],
    "sn": ["sn(ncomp,nx,ny,nz)"],
    "sp10": ["sp10(ncomp+nspec,0:nx+1,ny,nz)",
             "sp10(ncomp+nspec,0:nx+1,0:ny+1,nz)",
             "sp10(ncomp+nspec,0:nx+1,ny,0:nz+1)",
             "sp10(ncomp+nspec,0:nx+1,0:ny+1,0:nz+1)"],
    # Declared (ncomp+nspec,nx,ny,nz) in both BOGLSource2026 and JennySource2025, but the shipped
    # binary writes ncomp+nspec by nx+2 -- the same shape as sp. Solving the x extent from the count
    # absorbs that; the declaration still fixes the axis order and the transverse extents.
    "spold": ["spold(ncomp+nspec,nx,ny,nz)"],
    "spex": ["spex(nexchange+nexch_sec,0:nx+1,ny,nz)",
             "spex(nexchange+nexch_sec,0:nx+1,0:ny+1,nz)",
             "spex(nexchange+nexch_sec,0:nx+1,ny,0:nz+1)",
             "spex(nexchange+nexch_sec,0:nx+1,0:ny+1,0:nz+1)"],
    "spex10": ["spex10(nexchange+nexch_sec,0:nx+1,ny,nz)",
               "spex10(nexchange+nexch_sec,0:nx+1,0:ny+1,nz)",
               "spex10(nexchange+nexch_sec,0:nx+1,ny,0:nz+1)",
               "spex10(nexchange+nexch_sec,0:nx+1,0:ny+1,0:nz+1)"],
    "gam": ["gam(ncomp+nspec,nx,ny,nz)"],
    "exchangesites": ["exchangesites(nexchange,nx,ny,nz)"],
    "spexold": ["spexold(nexchange+nexch_sec,nx,ny,nz)"],
    "spgas": ["spgas(ngas,0:nx+1,ny,nz)",
              "spgas(ngas,0:nx+1,0:ny+1,nz)",
              "spgas(ngas,0:nx+1,ny,0:nz+1)",
              "spgas(ngas,0:nx+1,0:ny+1,0:nz+1)"],
    "spgasold": ["spgasold(ngas,nx,ny,nz)"],
    "spgas10": ["spgas10(ngas,0:nx+1,ny,nz)",
                "spgas10(ngas,0:nx+1,0:ny+1,nz)",
                "spgas10(ngas,0:nx+1,ny,0:nz+1)",
                "spgas10(ngas,0:nx+1,0:ny+1,0:nz+1)"],
    "sgas": ["sgas(ncomp,nx,ny,nz)"],
    "sgasn": ["sgasn(ncomp,nx,ny,nz)"],
    "ssurf": ["ssurf(nsurf,nx,ny,nz)"],
    "ssurfn": ["ssurfn(nsurf,nx,ny,nz)"],
    "sexold": ["sexold(ncomp,nx,ny,nz)"],
    "ssurfold": ["ssurfold(ncomp,nx,ny,nz)"],
    "spsurf": ["spsurf(nsurf+nsurf_sec,0:nx+1,ny,nz)",
               "spsurf(nsurf+nsurf_sec,0:nx+1,0:ny+1,nz)",
               "spsurf(nsurf+nsurf_sec,0:nx+1,ny,0:nz+1)",
               "spsurf(nsurf+nsurf_sec,0:nx+1,0:ny+1,0:nz+1)"],
    "spsurf10": ["spsurf10(nsurf+nsurf_sec,0:nx+1,ny,nz)",
                 "spsurf10(nsurf+nsurf_sec,0:nx+1,0:ny+1,nz)",
                 "spsurf10(nsurf+nsurf_sec,0:nx+1,ny,0:nz+1)",
                 "spsurf10(nsurf+nsurf_sec,0:nx+1,0:ny+1,0:nz+1)"],
    "spsurfold": ["spsurfold(nsurf+nsurf_sec,nx,ny,nz)"],
    "raq_tot": ["raq_tot(ikin,nx,ny,nz)"],
    "sion": ["sion(nx,ny,nz)"],
    "jinit": ["jinit(nx,ny,nz)"],
    "keqmin": ["keqmin(nreactmax,nrct,nx,ny,nz)"],
    "volfx": ["volfx(nrct,0:nx,ny,nz)"],
    "dppt": ["dppt(nrct,nx,ny,nz)"],
    "area": ["area(nrct,nx,ny,nz)"],
    "LogPotential": ["LogPotential(nsurf,nx,ny,nz)",
                     "LogPotential(nsurf,0:nx+1,ny,nz)",
                     "LogPotential(nsurf,0:nx+1,0:ny+1,nz)",
                     "LogPotential(nsurf,0:nx+1,ny,0:nz+1)",
                     "LogPotential(nsurf,0:nx+1,0:ny+1,0:nz+1)"],
    "t": ["t(0:nx+1,ny,nz)",
          "t(0:nx+1,0:ny+1,nz)",
          "t(0:nx+1,ny,0:nz+1)",
          "t(0:nx+1,0:ny+1,0:nz+1)"],
    "told": ["told(nx,ny,nz)"],
    "ro": ["ro(-1:nx+2,-1:ny+2,-1:nz+2)"],
    "por": ["por(-1:nx+2,-1:ny+2,-1:nz+2)"],
    "satliq": ["satliq(-1:nx+2,-1:ny+2,-1:nz+2)"],
    "qxgas": ["qxgas(0:nx,ny,nz)"],
    "qygas": ["qygas(nx,0:ny,nz)"],
    "qzgas": ["qzgas(nx,ny,0:nz)"],
    "pres": ["pres(0:nx+1,0:ny+1,0:nz+1)"],
    "dspy": ["dspy(nx,ny,nz)"],
    "dspz": ["dspz(nx,ny,nz)"],
    "qg": ["qg(nx,ny,nz)"],
    "ActiveCell": ["ActiveCell(nx,ny,nz)"],
    "VolSaveByTimeStep": ["VolSaveByTimeStep(101,nrct,0:nx,ny,nz)"],
    "Volsave": ["Volsave(nrct,0:nx,ny,nz)"],
}


class RstError(RuntimeError):
    """Raised when a restart file cannot be parsed or regridded safely.

    A ``RuntimeError`` rather than a ``ValueError`` so that a caller driving a staged chain can tell
    a restart-file problem from a CrunchTope failure, which surfaces as a non-zero ``error_code`` on
    the InputFile rather than as an exception.
    """


# --------------------------------------------------------------------------- #
# Fortran unformatted sequential I/O
# --------------------------------------------------------------------------- #

def read_records(path: Path) -> tuple[bytes, list[tuple[int, int]]]:
    """Return file contents plus ``(offset, nbytes)`` for each record.

    Records are bracketed by identical 4-byte length markers; a mismatch means the file is not
    4-byte-marker unformatted sequential, or is truncated.
    """
    path = Path(path)
    buf = path.read_bytes()
    if not buf:
        raise RstError(f"{path} is empty")

    records: list[tuple[int, int]] = []
    off = 0
    while off < len(buf):
        if off + MARKER_SIZE > len(buf):
            raise RstError(f"truncated leading marker at byte {off}")
        (nbytes,) = MARKER.unpack_from(buf, off)
        if nbytes < 0:
            raise RstError(
                f"negative record length {nbytes} at byte {off}: the file may use subrecords "
                "(>2 GB records) or a different marker width"
            )
        data, tail = off + MARKER_SIZE, off + MARKER_SIZE + nbytes
        if tail + MARKER_SIZE > len(buf):
            raise RstError(f"record at byte {off} runs past end of file")
        (check,) = MARKER.unpack_from(buf, tail)
        if check != nbytes:
            raise RstError(
                f"record marker mismatch at byte {off}: leading {nbytes}, trailing {check}"
            )
        records.append((data, nbytes))
        off = tail + MARKER_SIZE
    return buf, records


def write_records(path: Path, payloads: list[bytes]) -> None:
    """Write *payloads* as Fortran unformatted sequential records."""
    with Path(path).open("wb") as fh:
        for payload in payloads:
            marker = MARKER.pack(len(payload))
            fh.write(marker)
            fh.write(payload)
            fh.write(marker)


# --------------------------------------------------------------------------- #
# Model dimensions
# --------------------------------------------------------------------------- #

def model_dimensions(input_deck: Path) -> dict[str, int]:
    """Count the species/reaction blocks of a CrunchTope input deck.

    Commented lines (leading ``!``) are excluded, so a deck carrying inactive scenario blocks gives
    the dimensions actually in force.

    Args:
        input_deck: Path to the CrunchTope input file.

    Returns:
        dict keyed by CrunchTope block name, e.g. ``{'PRIMARY_SPECIES': 23, ...}``.
    """
    text = Path(input_deck).read_text(errors="replace")
    dims: dict[str, int] = {}
    for block in _DIM_BLOCKS:
        match = re.search(rf"^[ \t]*{re.escape(block)}[ \t]*$(.*?)^[ \t]*END",
                          text, re.M | re.S | re.I)
        dims[block] = 0 if match is None else sum(
            1 for line in match.group(1).splitlines()
            if line.strip() and not line.strip().startswith("!")
        )
    return dims


def dims_from_input_file(input_file) -> dict[str, int]:
    """Count the same blocks from an already-parsed Omphalos InputFile or Template.

    Preferred over :func:`model_dimensions` inside Omphalos, which has parsed the deck once already.

    The block's own name is the first key of its ``contents``, an artefact of how
    ``InputFile.get_keyword_block`` stores it, so the species count is one less than ``len``.
    Getting that wrong gives ``ncomp + 1``, which is exactly the off-by-one that makes ``s``
    decompose plausibly and wrongly.

    Args:
        input_file: An InputFile (or Template) whose keyword blocks have been read.

    Returns:
        dict keyed by CrunchTope block name, as :func:`model_dimensions` returns.
    """
    dims: dict[str, int] = {}
    for block in _DIM_BLOCKS:
        keyword_block = input_file.keyword_blocks.get(block)
        if keyword_block is None or not keyword_block.contents:
            dims[block] = 0
            continue
        entries = [name for name in keyword_block.contents if name != block]
        dims[block] = len(entries)
    return dims


def known_leads(dims: dict[str, int] | None) -> frozenset[int]:
    """Plausible sizes for a leading (non-x) component axis, used by the fallback only."""
    leads = {1}
    if dims:
        ncomp = dims.get("PRIMARY_SPECIES", 0)
        nspec = dims.get("SECONDARY_SPECIES", 0)
        for value in (ncomp, nspec, ncomp + nspec,
                      dims.get("AQUEOUS_KINETICS", 0),
                      dims.get("MINERALS", 0), dims.get("GASES", 0)):
            if value > 0:
                leads.add(value)
    return frozenset(leads)


def _symbol_values(dims: dict[str, int] | None) -> dict[str, int]:
    """Translate the block-name dict into the Fortran dimension symbols.

    A block the deck does not declare contributes zero, not nothing. Dropping it instead leaves
    ``ncomp+nspec`` unresolvable for a model with no secondary species, and an unresolvable leading
    axis is treated as free -- which lets a spurious decomposition win. Measured on a 3-primary,
    0-secondary column: ``sp`` came out as ``(nx+2, 3)`` with x on axis 0 rather than
    ``(3, nx+2)`` with x on axis 1, and the restart it produced diverged to NaN on the first step.
    """
    if not dims:
        return {}
    return {symbol: dims[block] for symbol, block in _SYMBOL_BLOCKS.items() if block in dims}


# --------------------------------------------------------------------------- #
# Layout inference
# --------------------------------------------------------------------------- #

@dataclass
class RecordSpec:
    """How one record decomposes with respect to the grid."""

    index: int
    name: str
    nbytes: int
    dtype: np.dtype
    count: int
    xdim: int | None = None
    pad: int = 0
    shape: tuple[int, ...] = ()
    xaxis: int | None = None
    #: Stored entries before the first physical cell. Taken from the declaration's lower bound
    #: rather than assumed to be half the padding, which is wrong for (-1:nx+1): that stores two
    #: entries before cell 1 and one after cell nx, where pad // 2 would say one and two.
    lead_ghost: int = 0
    ambiguous: bool = False
    source: str = "none"
    notes: list[str] = field(default_factory=list)

    @property
    def grid_dependent(self) -> bool:
        return self.xaxis is not None

    def describe(self) -> str:
        if not self.grid_dependent:
            kind = "header" if self.name in HEADER_RECORDS else "grid-independent"
            return f"{kind}, {self.count} elt"
        shape = ", ".join(
            f"[{n}]" if i == self.xaxis else str(n) for i, n in enumerate(self.shape)
        )
        pad = {0: "cell-centred", 1: "face (0:nx)", 2: "ghost (0:nx+1)",
               3: "ghost (-1:nx+1)", 4: "ghost (-1:nx+2)"}.get(self.pad, f"pad={self.pad}")
        return f"({shape}) F-order, x=axis{self.xaxis}, {pad}"


@dataclass(frozen=True)
class _Axis:
    """One axis of a Fortran declaration."""

    text: str
    grid: str | None      # 'x', 'y', 'z' if the bound names a grid dimension, else None
    lo: int               # lower bound, as declared
    offset: int           # upper bound relative to the grid dimension (0 for 'nx')
    symbol: str | None    # dimension symbol(s) for a non-grid axis, e.g. 'ncomp+nspec'
    literal: int | None   # fixed extent for a literal axis, e.g. 101


_BOUND = re.compile(r"^(?:(-?\d+):)?(.+)$")


def _parse_axis(text: str) -> _Axis:
    """Classify one comma-separated term of an ALLOCATE declaration."""
    text = text.strip()
    match = _BOUND.match(text)
    lo = int(match.group(1)) if match.group(1) else 1
    upper = match.group(2).strip()

    grid_match = re.match(r"^n([xyz])(?:\s*\+\s*(\d+))?$", upper)
    if grid_match:
        return _Axis(text, grid_match.group(1), lo,
                     int(grid_match.group(2) or 0), None, None)
    if upper.isdigit():
        return _Axis(text, None, lo, 0, None, int(upper) - lo + 1)
    return _Axis(text, None, lo, 0, upper.replace(" ", ""), None)


def _parse_declaration(declaration: str) -> list[_Axis]:
    """Split ``name(a,b,c)`` into its axes, in Fortran order."""
    body = declaration[declaration.index("(") + 1:declaration.rindex(")")]
    return [_parse_axis(term) for term in body.split(",")]


def _axis_extent(axis: _Axis, nx: int) -> int:
    """Extent of a non-x axis, for a 1-D column where ``ny == nz == 1``."""
    if axis.grid == "x":
        return nx + axis.offset - axis.lo + 1
    if axis.grid in ("y", "z"):
        return 1 + axis.offset - axis.lo + 1
    return axis.literal if axis.literal is not None else 0


def _symbol_product(symbol: str, symbols: dict[str, int]) -> int | None:
    """Value of a ``a+b`` dimension expression, or None if any term is unknown."""
    total = 0
    for term in symbol.split("+"):
        if term not in symbols:
            return None
        total += symbols[term]
    return total


def _from_declaration(spec: RecordSpec, nx: int, symbols: dict[str, int]) -> bool:
    """Fill *spec* from its declared shape, solving the x extent from the element count.

    Returns True if a consistent shape was found. The declaration fixes which axis is x and what the
    transverse extents are; the x extent is solved rather than asserted, because the shipped binary
    does not always match the checked-out source (``spold`` is declared ``nx`` and written
    ``nx+2``). A record whose count cannot be reconciled with any declared variant leaves the spec
    unset, and the caller falls back to factorisation.
    """
    candidates = []
    for declaration in DECLARATIONS.get(spec.name, []):
        axes = _parse_declaration(declaration)
        x_positions = [i for i, axis in enumerate(axes) if axis.grid == "x"]
        if len(x_positions) != 1:
            continue
        x_at = x_positions[0]

        # Everything before x multiplies into a single leading axis; everything after it is
        # transverse. Fortran is column-major, so this preserves the memory layout exactly.
        lead_known = 1
        lead_free = False
        for axis in axes[:x_at]:
            if axis.symbol is not None:
                value = _symbol_product(axis.symbol, symbols)
                if value is None:
                    lead_free = True
                else:
                    lead_known *= value
            else:
                lead_known *= _axis_extent(axis, nx)

        trail_dims = tuple(_axis_extent(axis, nx) for axis in axes[x_at + 1:])
        trail = int(np.prod(trail_dims)) if trail_dims else 1
        if trail <= 0 or lead_known <= 0:
            continue

        declared_xdim = _axis_extent(axes[x_at], nx)
        # Entries stored before cell 1: '(0:nx+1)' keeps one, '(-1:nx+2)' and '(-1:nx+1)' keep two.
        lead_ghost = max(0, 1 - axes[x_at].lo)
        for xdim in range(nx, nx + MAX_PAD + 1):
            denominator = xdim * trail * lead_known
            if denominator <= 0 or spec.count % denominator:
                continue
            free = spec.count // denominator
            if free != 1 and not lead_free:
                continue
            candidates.append((0 if xdim == declared_xdim else 1, abs(xdim - declared_xdim),
                               xdim, lead_known * free, trail_dims, declaration, declared_xdim,
                               lead_ghost))

    if not candidates:
        return False

    candidates.sort()
    _, _, xdim, lead, trail_dims, declaration, declared_xdim, lead_ghost = candidates[0]

    spec.xdim, spec.pad, spec.source = xdim, xdim - nx, "declaration"
    # The declared lower bound is only usable if the declared extent was the one found. Where the
    # extent had to be solved, the declaration is out of date for this array and says nothing about
    # where its extra entries went, so fall back to assuming they are split evenly. For spold --
    # declared (ncomp+nspec,nx) and written with nx+2 -- that recovers the same one-ghost-each-side
    # layout as sp, which is what the binary actually writes and what the consistency pass needs.
    spec.lead_ghost = lead_ghost if xdim == declared_xdim else (xdim - nx) // 2
    tail = tuple(extent for extent in trail_dims if extent > 1)
    if lead == 1:
        spec.shape, spec.xaxis = (xdim,) + tail, 0
    else:
        spec.shape, spec.xaxis = (lead, xdim) + tail, 1

    if xdim != declared_xdim:
        spec.notes.append(
            f"x extent {xdim} solved from the record; {declaration} declares {declared_xdim}. "
            "The build differs from the source the table was taken from."
        )
    # Rivals that disagree about the memory layout, rather than merely about which transverse axis
    # carries the ghosts, mean the declaration did not settle the shape.
    distinct = {(c[2], c[3]) for c in candidates}
    if len(distinct) > 1:
        spec.ambiguous = True
        spec.notes.append(f"declared variants disagree: {sorted(distinct)}")
    return True


def _divisors(n: int) -> list[int]:
    out: set[int] = set()
    i = 1
    while i * i <= n:
        if n % i == 0:
            out.add(i)
            out.add(n // i)
        i += 1
    return sorted(out)


def _record_names(n_records: int) -> list[str]:
    """Map the record count onto the writer's conditional blocks."""
    options = ([], _SATURATE, _ERODE, _SATURATE + _ERODE)
    for extra in options:
        names = _BASE + extra + _TAIL
        if len(names) == n_records:
            return names
    expected = sorted(len(_BASE + e + _TAIL) for e in options)
    raise RstError(
        f"{n_records} records matches no expected CrunchTope layout (expected one of {expected}); "
        "the writer in CrunchTope.F90 may have changed"
    )


def _candidates(count: int, nx: int, leads: frozenset[int]):
    """Yield ``(key, xdim, pad, lead, trail)`` shape candidates, best first."""
    found = []
    for xdim in _divisors(count):
        if not nx <= xdim <= nx + MAX_PAD:
            continue
        rest = count // xdim
        for trail in _divisors(rest):
            if trail not in TRANSVERSE_OK:
                continue
            lead = rest // trail
            key = (xdim - nx, 0 if lead in leads else 1, trail, lead)
            found.append((key, xdim, xdim - nx, lead, trail))
    found.sort()
    return found


def _factor_trail(trail: int) -> tuple[int, ...]:
    """Split a transverse product back into per-dimension extents."""
    if trail == 1:
        return ()
    for a in _TRANSVERSE_DIMS:
        if a > 1 and trail % a == 0 and trail // a in _TRANSVERSE_DIMS and trail // a > 1:
            return (a, trail // a)
    return (trail,)


def _from_factorisation(spec: RecordSpec, nx: int, leads: frozenset[int]) -> bool:
    """Fill *spec* by factorising its element count. Fallback only -- see the module docstring."""
    cands = _candidates(spec.count, nx, leads)
    if not cands:
        return False
    _, xdim, pad, lead, trail = cands[0]
    spec.xdim, spec.pad, spec.source = xdim, pad, "factorisation"
    # No declaration to read the lower bound from, so fall back to assuming symmetric padding.
    spec.lead_ghost = pad // 2
    tail = _factor_trail(trail)
    if lead == 1:
        spec.shape, spec.xaxis = (xdim,) + tail, 0
    else:
        spec.shape, spec.xaxis = (lead, xdim) + tail, 1
    spec.notes.append("no declaration for this record; shape guessed by factorisation")
    # Any rival at all is a real ambiguity here: the ranking that separates them is a heuristic, and
    # at small nx it picks wrong.
    if len(cands) > 1:
        spec.ambiguous = True
        spec.notes.append(f"rival shape lead={cands[1][3]} xdim={cands[1][1]} trail={cands[1][4]}")
    return True


def infer_layout(path: Path, nx: int, dims: dict[str, int] | None = None) -> list[RecordSpec]:
    """Infer the grid decomposition of every record in *path*.

    Args:
        path: The ``.rst`` file to read.
        nx: Number of grid cells the file was written on.
        dims: Block counts as :func:`model_dimensions` returns. Strongly recommended: without them
            the leading axis sizes are unknown and several records cannot be resolved.

    Returns:
        list of RecordSpec, in record order.
    """
    if nx < 2:
        raise RstError(f"nx must be at least 2, got {nx}")
    leads = known_leads(dims)
    symbols = _symbol_values(dims)
    _, records = read_records(path)
    names = _record_names(len(records))

    specs: list[RecordSpec] = []
    for index, ((_, nbytes), name) in enumerate(zip(records, names)):
        dtype = np.dtype(np.int32 if name in INT_RECORDS else np.float64)
        if nbytes % dtype.itemsize:
            raise RstError(f"record {index} ({name}): {nbytes} bytes is not a whole number of "
                           f"{dtype} elements")
        spec = RecordSpec(index, name, nbytes, dtype, nbytes // dtype.itemsize)

        if spec.count and name not in HEADER_RECORDS:
            resolved = _from_declaration(spec, nx, symbols)
            if not resolved:
                resolved = _from_factorisation(spec, nx, leads)
            if not resolved and spec.count > 1:
                spec.notes.append("no x decomposition found; copied verbatim "
                                  "(a regrid will produce a corrupt file)")
        specs.append(spec)
    return specs


# --------------------------------------------------------------------------- #
# Resampling
# --------------------------------------------------------------------------- #

def cell_widths(zones, nx: int) -> np.ndarray:
    """Per-cell widths from an ``xzones`` specification.

    ``xzones`` is a sequence of (cell count, cell width) pairs, so a graded grid such as
    ``xzones 20 5.0 100 0.5 20 5.0`` -- coarse, fine, coarse -- gives 140 cells of three different
    widths. A trailing count with no width takes unit width, as CrunchTope's default.

    Args:
        zones: The tokens following the xzones keyword, or None for a uniform grid.
        nx: Total cell count, used when *zones* is None or does not account for every cell.

    Returns:
        Array of nx cell widths.
    """
    if not zones:
        return np.ones(nx)

    widths = []
    for index in range(0, len(zones), 2):
        count = int(float(zones[index]))
        width = float(zones[index + 1]) if index + 1 < len(zones) else 1.0
        widths.extend([width] * count)

    if len(widths) != nx:
        raise RstError(
            f"xzones declares {len(widths)} cells but nx is {nx}; the grid specification and the "
            "cell count disagree"
        )

    return np.asarray(widths, dtype=float)


def _edges(nx: int, zones=None) -> np.ndarray:
    """Normalised positions of the nx+1 cell faces, spanning [0, 1].

    Normalising by the column's own length means a grid change is interpreted as a change of
    resolution over the same column, which is what a refinement chain means by it. Absolute lengths
    would make a chain that also rescales the domain interpolate into empty space.
    """
    edges = np.concatenate(([0.0], np.cumsum(cell_widths(zones, nx))))

    return edges / edges[-1]


def _coords(n_interior: int, pad: int, lead_ghost: int | None = None, zones=None) -> np.ndarray:
    """Normalised coordinates of the stored positions along x.

    Face-centred data (``pad == 1``) sits on the cell faces; everything else sits at cell centres,
    with ghost cells placed one cell width beyond the edge -- the *edge cell's* width, so a graded
    grid puts them where the array actually reaches.

    Args:
        n_interior: Number of physical cells.
        pad: Total number of stored entries beyond the physical cells.
        lead_ghost: How many of them precede the first physical cell. Defaults to ``pad // 2``,
            which is right for every symmetric case but not for ``(-1:nx+1)``.
        zones: The xzones tokens, or None for a uniform grid.
    """
    edges = _edges(n_interior, zones)
    if pad == 1:
        return edges

    centres = 0.5 * (edges[:-1] + edges[1:])
    if pad == 0:
        return centres

    widths = np.diff(edges)
    lead = pad // 2 if lead_ghost is None else lead_ghost
    trail = pad - lead

    before = [centres[0] - widths[0] * (offset + 1) for offset in reversed(range(lead))]
    after = [centres[-1] + widths[-1] * (offset + 1) for offset in range(trail)]

    return np.concatenate([before, centres, after])


def resample(values: np.ndarray, spec: RecordSpec, nx_in: int, nx_out: int,
             zones_in=None, zones_out=None) -> np.ndarray:
    """Resample *values* along the x axis of *spec* from *nx_in* to *nx_out*.

    Pass *zones_in* and *zones_out* -- the two grids' ``xzones`` tokens -- when either grid is
    graded. Without them both grids are taken as uniform, and a graded grid would be resampled by
    cell index rather than by position, which misplaces every value outside the uniform zone.
    """
    if spec.xaxis is None:
        return values
    src = _coords(nx_in, spec.pad, spec.lead_ghost, zones_in)
    dst = _coords(nx_out, spec.pad, spec.lead_ghost, zones_out)
    if len(src) != values.shape[spec.xaxis]:
        raise RstError(
            f"record {spec.index} ({spec.name}): x extent {values.shape[spec.xaxis]} does not "
            f"match nx_in={nx_in} with pad={spec.pad}"
        )

    work = np.moveaxis(values, spec.xaxis, 0)
    flat = np.ascontiguousarray(work).reshape(len(src), -1)
    if spec.name in NEAREST_RECORDS or spec.dtype.kind in "iu":
        idx = np.abs(dst[:, None] - src[None, :]).argmin(axis=1)
        out = flat[idx]
    else:
        out = np.empty((len(dst), flat.shape[1]), dtype=np.float64)
        for col in range(flat.shape[1]):
            out[:, col] = np.interp(dst, src, flat[:, col])
    out = out.reshape((len(dst),) + work.shape[1:]).astype(spec.dtype)
    return np.moveaxis(out, 0, spec.xaxis)


def load_record(buf: bytes, offset: int, spec: RecordSpec) -> np.ndarray:
    """Read one record as a Fortran-ordered array of its inferred shape."""
    arr = np.frombuffer(buf, dtype=spec.dtype, count=spec.count, offset=offset)
    return arr.reshape(spec.shape, order="F") if spec.grid_dependent else arr


def interior_profile(arr: np.ndarray, spec: RecordSpec, nx: int, component: int = 0) -> np.ndarray:
    """Interior x profile of one component.

    Transverse axes carry their own ghost layers -- extent 3 is ``0:ny+1`` and extent 5 is
    ``-1:ny+2`` -- so the physical slice is the middle index, not index 0. Selecting index 0 samples
    a ghost layer, which for ``s`` is filled with zeros.
    """
    index = []
    for axis, extent in enumerate(spec.shape):
        if axis == spec.xaxis:
            index.append(slice(None))
        elif axis == 0 and spec.xaxis == 1:
            index.append(min(component, extent - 1))       # component axis
        else:
            index.append((extent - 1) // 2 if extent in (3, 5) else 0)
    series = np.asarray(arr[tuple(index)])
    if spec.pad == 1:
        return series
    lo = spec.lead_ghost
    return series[lo:lo + nx]


def inject_field(arr: np.ndarray, spec: RecordSpec, nx: int, values: np.ndarray) -> np.ndarray:
    """Overwrite the x profile of *spec* with *values*, replicating ghosts.

    ``CALL restart`` runs *after* ``CALL StartTope`` in ``CrunchTope.F90``, so a field stored in the
    restart file overrides whatever the input deck read from disk. For porosity that matters: a
    resampled ``por`` is a linear interpolation of the coarse profile, which silently supersedes the
    intended ``read_PorosityFile`` values on the fine grid.

    Extents come from *arr*, not from ``spec.shape``. A regrid injects into an array that has
    already been resampled onto ``nx``, while the spec still describes the source grid, so trusting
    the spec's x extent leaves the trailing ghost cells holding the old interpolated values -- the
    boundary corruption this function exists to prevent.
    """
    if len(values) != nx:
        raise RstError(f"field for {spec.name!r} has {len(values)} values, expected {nx}")
    out = np.array(arr, copy=True)
    axis = spec.xaxis
    ndim = out.ndim
    lo = 0 if spec.pad == 1 else spec.lead_ghost
    if lo + nx > out.shape[axis]:
        raise RstError(
            f"record {spec.name!r}: {nx} cells with pad={spec.pad} do not fit an x extent of "
            f"{out.shape[axis]}"
        )

    shaped = values.reshape(tuple(-1 if a == axis else 1 for a in range(ndim)))
    sl = tuple(slice(lo, lo + nx) if a == axis else slice(None) for a in range(ndim))
    out[sl] = np.broadcast_to(shaped, out[sl].shape)

    # Replicate the edge values into any leading/trailing ghost cells.
    def _at(index):
        return tuple(index if a == axis else slice(None) for a in range(ndim))

    for ghost in range(lo):
        out[_at(ghost)] = out[_at(lo)]
    for ghost in range(lo + nx, out.shape[axis]):
        out[_at(ghost)] = out[_at(lo + nx - 1)]
    return out


def _interior_slice(spec: RecordSpec, nx: int) -> tuple:
    """Index tuple selecting the physical cells, x restricted, others full."""
    lo = 0 if spec.pad == 1 else spec.lead_ghost
    return tuple(slice(lo, lo + nx) if axis == spec.xaxis else slice(None)
                 for axis in range(len(spec.shape)))


def master_index(deck: Path | None, dims: dict[str, int] | None = None) -> int:
    """Index of the timestep-control master species within the primary list.

    Mirrors ``StartTope.F90``: ``H+`` is chosen if present, then *overridden* by ``O2(aq)`` if that
    is also a primary species, and an explicit ``master_variable`` / ``master`` keyword beats both.
    Returns 0 if it cannot be determined -- that only mis-aims the timestep controller's diagnostic,
    it does not affect the governing equations.
    """
    if deck is None:
        return 0
    text = Path(deck).read_text(errors="replace")
    match = re.search(r"^[ \t]*PRIMARY_SPECIES[ \t]*$(.*?)^[ \t]*END", text, re.M | re.S | re.I)
    if match is None:
        return 0
    primaries = [line.strip() for line in match.group(1).splitlines()
                 if line.strip() and not line.strip().startswith("!")]

    explicit = re.search(r"^[ \t]*master(?:_variable)?[ \t]+(\S+)", text, re.M | re.I)
    wanted = [explicit.group(1)] if explicit else [n for n in ("H+", "O2(aq)") if n in primaries]
    for name in reversed(wanted):          # later candidates win, as in source
        if name in primaries:
            return primaries.index(name)
    return 0


def enforce_consistency(arrays: dict[str, np.ndarray], specs: dict[str, RecordSpec], nx: int,
                        ikmast: int = 0) -> list[str]:
    """Re-derive the dependent state arrays so the restart is self-consistent.

    ``sp``, ``sp10``, ``s``, ``sn``, ``spold``, ``spnO2`` and ``spnnO2`` are not independent:
    ``sp10 == exp(sp)`` exactly, ``s`` is a *linear* combination of the species concentrations in
    ``sp10``, and ``sn``/``spold``/``spnnO2`` are the previous step's copies. Resampling each one
    separately breaks all three relations, and GIMRT's residual carries a ``(s - sn)/delt`` term, so
    with a small ``timestep_init`` any mismatch is amplified without bound and Newton fails on the
    first step.

    ``sp10`` is treated as authoritative because linear interpolation commutes with the linear
    total-forming operation, so linearly resampled ``sp10`` and ``s`` stay mutually consistent;
    ``sp`` is then recovered as its log. The previous-step arrays are set equal to the current ones,
    which is also the physically honest statement -- the state is being presented as a starting
    point, not mid-step. Setting ``spnO2 == spnnO2`` additionally zeroes the curvature estimate in
    ``timestep.F90``, so the step ramps up cleanly from ``timestep_init`` instead of inheriting a
    stale second derivative.

    Returns the names of the records it rewrote.
    """
    done: list[str] = []

    if "sp10" in arrays and "sp" in arrays:
        # Interior only. In a CrunchTope-written file the ghost entries of both sp and sp10 are 0.0
        # (never initialised -- exp(0) = 1, so they are not a consistent log/linear pair), and they
        # hold Dirichlet boundary values once the run is going. Leave them exactly as resampled
        # rather than writing ln(1e-30) into the boundary storage.
        #
        # Clip sp10 as well as flooring the log so exp(sp) == sp10 holds exactly, not merely above
        # the floor. Cells below 1e-30 mol/kg are already at CrunchTope's own floor, and raising
        # them perturbs the totals in `s` by ~1e-30 against values of order 1e-3.
        sl = _interior_slice(specs["sp10"], nx)
        arrays["sp10"][sl] = np.maximum(arrays["sp10"][sl], CONC_FLOOR)
        arrays["sp"][_interior_slice(specs["sp"], nx)] = np.log(arrays["sp10"][sl])
        done.extend(("sp10", "sp"))
    if "spold" in arrays and "sp" in arrays and arrays["spold"].shape == arrays["sp"].shape:
        arrays["spold"] = arrays["sp"].copy()
        done.append("spold")

    # sn is s restricted to the interior of every axis but the components.
    if "sn" in arrays and "s" in arrays:
        s_spec = specs["s"]
        lo = s_spec.lead_ghost
        index = [slice(None)]
        for axis, extent in enumerate(s_spec.shape):
            if axis == 0:
                continue
            if axis == s_spec.xaxis:
                index.append(slice(lo, lo + nx))
            else:
                index.append((extent - 1) // 2 if extent in (3, 5) else 0)
        candidate = np.asarray(arrays["s"][tuple(index)])
        if candidate.shape == arrays["sn"].shape:
            arrays["sn"] = candidate.copy()
            done.append("sn")

    # Master-variable history: both previous copies equal the current value.
    if "sp" in arrays:
        sp_spec = specs["sp"]
        lo = sp_spec.lead_ghost
        row = min(ikmast, arrays["sp"].shape[0] - 1)
        master = np.asarray(arrays["sp"][row, lo:lo + nx])
        for name in ("spnO2", "spnnO2"):
            if name in arrays and arrays[name].shape == master.shape:
                arrays[name] = master.copy()
                done.append(name)
    return done


def regrid(path: Path, nx_in: int, nx_out: int, out: Path, dims: dict[str, int] | None = None,
           set_dtmax: float | None = None, set_dtold: float | None = None,
           set_time: float | None = None, allow_unresolved: bool = False,
           inject: dict[str, np.ndarray] | None = None, consistent: bool = True,
           deck: Path | None = None, zones_in=None,
           zones_out=None) -> tuple[list[RecordSpec], list[str]]:
    """Write *path* resampled from *nx_in* to *nx_out* cells into *out*.

    Args:
        path: Source ``.rst``.
        nx_in: Cell count the source was written on.
        nx_out: Cell count to resample onto.
        out: Destination path.
        dims: Block counts, as :func:`model_dimensions` or :func:`dims_from_input_file` returns.
        set_dtmax: Override the stored ``dtmax``. ``restart.F90`` takes it from the file, so
            ``timestep_max`` in the new deck is otherwise ignored.
        set_dtold: Override the stored ``dtold``.
        set_time: Override the stored simulated time.
        allow_unresolved: Copy undecomposable records verbatim instead of refusing. Unsafe.
        inject: Maps record names to ``nx_out``-length profiles that replace the resampled values.
            Use it for porosity, which the restart would otherwise override on the fine grid.
        consistent: Re-derive the dependent state arrays (see :func:`enforce_consistency`). Leave on
            unless deliberately inspecting the raw resampling.
        deck: Input deck, read only to locate the master variable for the consistency pass.
        zones_in: The source grid's xzones tokens. Needed only if that grid is graded; without it
            the grid is taken as uniform.
        zones_out: The target grid's xzones tokens, likewise.

    Returns:
        ``(specs, rewritten)``, where *rewritten* names the records the consistency pass replaced.
    """
    # Positions are normalised by each grid's own length, so a chain that changes the column length
    # as well as its resolution stretches the old solution over the new domain rather than failing.
    # That is occasionally what is wanted and usually a typo in the zone widths, so say so.
    if zones_in and zones_out:
        length_in = float(cell_widths(zones_in, nx_in).sum())
        length_out = float(cell_widths(zones_out, nx_out).sum())
        if abs(length_out - length_in) > 1e-6 * max(length_in, length_out):
            logger.warning(
                "grid length changes from %g to %g: the solution will be stretched over the new "
                "domain, not placed at the same physical depths. Check the xzones widths.",
                length_in, length_out)

    specs = infer_layout(path, nx_in, dims)
    broken = [s.name for s in specs
              if not s.grid_dependent and s.count > 1 and s.name not in HEADER_RECORDS and s.notes]
    if broken and not allow_unresolved:
        raise RstError(
            f"cannot regrid: no x decomposition for {broken}. Pass the CrunchTope deck so the "
            "leading axis sizes are known, or allow_unresolved=True to copy them verbatim (unsafe)."
        )

    buf, records = read_records(path)

    # Pass 1: resample every grid-dependent record, keeping the arrays so the consistency pass can
    # see across records.
    verbatim: dict[int, bytes] = {}
    arrays: dict[str, np.ndarray] = {}
    for spec, (offset, nbytes) in zip(specs, records):
        if not spec.grid_dependent:
            payload = buf[offset:offset + nbytes]
            if spec.name == "tsteps" and (set_dtmax is not None or set_dtold is not None):
                vals = list(struct.unpack("<6d", payload))
                if set_dtold is not None:
                    vals[1] = set_dtold
                if set_dtmax is not None:
                    vals[5] = set_dtmax
                payload = struct.pack("<6d", *vals)
            elif spec.name == "time" and set_time is not None:
                payload = struct.pack("<d", set_time)
            verbatim[spec.index] = payload
            continue
        resampled = resample(load_record(buf, offset, spec), spec, nx_in, nx_out,
                             zones_in, zones_out)
        if inject and spec.name in inject:
            resampled = inject_field(resampled, spec, nx_out, inject[spec.name])
        arrays[spec.name] = resampled

    # Pass 2: re-derive the dependent arrays.
    rewritten: list[str] = []
    if consistent:
        by_name = {s.name: s for s in specs if s.grid_dependent}
        rewritten = enforce_consistency(arrays, by_name, nx_out, master_index(deck, dims))

    # Pass 3: serialise in record order.
    payloads = [
        verbatim[spec.index] if spec.index in verbatim
        else np.asfortranarray(arrays[spec.name].astype(spec.dtype)).tobytes(order="F")
        for spec in specs
    ]
    write_records(out, payloads)
    return specs, rewritten


# --------------------------------------------------------------------------- #
# Verification
# --------------------------------------------------------------------------- #

#: ``(tecplot stem, record, first data column, transform)``.
REFERENCE_CHECKS = (
    ("porosity", "por", 3, None),
    ("totcon", "s", 3, None),
    ("conc", "sp", 3, "ln10"),
)


def verify_identity(path: Path, nx: int, dims: dict[str, int] | None = None) -> bool:
    """Regrid ``nx -> nx`` and report whether the result is byte-identical.

    Runs with ``consistent=False``: the consistency pass deliberately rewrites the dependent arrays,
    so it would defeat a bit-for-bit comparison. This check exists to validate the
    parse/reshape/resample/write path.
    """
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".identity.tmp")
    try:
        regrid(path, nx, nx, tmp, dims, consistent=False)
        return tmp.read_bytes() == path.read_bytes()
    finally:
        tmp.unlink(missing_ok=True)


def consistency_report(path: Path, nx: int, dims: dict[str, int] | None = None) -> dict[str, float]:
    """Measure the state invariants a restart depends on.

    ``s_vs_sn`` is the one that decides whether GIMRT can start: the residual carries
    ``(s - sn)/delt``, so a mismatch is amplified by a small ``timestep_init``. ``sp10_vs_exp_sp``
    should be exactly zero.

    Distinguish the two kinds of entry when reporting. ``sp10_vs_exp_sp`` is a true invariant of any
    valid file; ``s_vs_sn`` and ``spnO2_vs_spnnO2`` are start conditions the regrid imposes, and a
    CrunchTope-written file legitimately violates them because it holds two real time levels.
    """
    specs = {s.name: s for s in infer_layout(path, nx, dims)}
    buf, records = read_records(path)

    def arr(name):
        spec = specs[name]
        return load_record(buf, records[spec.index][0], spec), spec

    out: dict[str, float] = {}
    if "s" in specs and "sn" in specs:
        s, s_spec = arr("s")
        sn, _ = arr("sn")
        lo = s_spec.lead_ghost
        index = [slice(None)]
        for axis, extent in enumerate(s_spec.shape):
            if axis == 0:
                continue
            index.append(slice(lo, lo + nx) if axis == s_spec.xaxis
                         else ((extent - 1) // 2 if extent in (3, 5) else 0))
        interior = np.asarray(s[tuple(index)])
        denom = np.maximum(np.abs(sn), CONC_FLOOR)
        out["s_vs_sn"] = float(np.max(np.abs(interior - sn) / denom))
    # Interior only: the ghost entries of a CrunchTope-written file are 0.0 for both sp and sp10,
    # which is not a consistent log/linear pair.
    if "sp" in specs and "sp10" in specs:
        sp, sp_spec = arr("sp")
        sp10, sp10_spec = arr("sp10")
        a = np.asarray(sp[_interior_slice(sp_spec, nx)])
        b = np.asarray(sp10[_interior_slice(sp10_spec, nx)])
        denom = np.maximum(np.abs(b), CONC_FLOOR)
        out["sp10_vs_exp_sp"] = float(np.max(np.abs(b - np.exp(a)) / denom))
    if "sp" in specs and "spold" in specs:
        sp, sp_spec = arr("sp")
        spold, spold_spec = arr("spold")
        interior_sp = np.asarray(sp[_interior_slice(sp_spec, nx)])
        interior_old = np.asarray(spold[_interior_slice(spold_spec, nx)])
        if interior_sp.shape == interior_old.shape:
            out["sp_vs_spold"] = float(np.max(np.abs(interior_sp - interior_old)))
    if "spnO2" in specs and "spnnO2" in specs:
        a, _ = arr("spnO2")
        b, _ = arr("spnnO2")
        out["spnO2_vs_spnnO2"] = float(np.max(np.abs(a - b)))
    return out


def verify_reference(path: Path, nx: int, tec_dir: Path, dims: dict[str, int] | None = None,
                     rtol: float = 1e-4, file_num: int = 1):
    """Compare stored arrays against the tecplot output beside the ``.rst``.

    Args:
        path: The ``.rst`` to check.
        nx: Cell count.
        tec_dir: Directory holding the tecplot output.
        dims: Block counts.
        rtol: Relative tolerance for a pass.
        file_num: Which tecplot output the restart corresponds to. A restart is written at the end
            of the run, so this is the *last* output number, not 1.

    Returns:
        list of ``(record, filename, max relative error, status)``.
    """
    specs = {s.name: s for s in infer_layout(path, nx, dims)}
    buf, records = read_records(path)
    results = []
    for stem, name, col, transform in REFERENCE_CHECKS:
        filename = f"{stem}{file_num}.tec"
        tec = Path(tec_dir) / filename
        if not tec.exists() or name not in specs:
            results.append((name, filename, None, "missing"))
            continue
        spec = specs[name]
        table = np.loadtxt(tec, skiprows=3)
        n_comp = table.shape[1] - col
        arr = load_record(buf, records[spec.index][0], spec)
        worst, worst_c = 0.0, -1
        for comp in range(min(n_comp, spec.shape[0] if spec.xaxis else 1)):
            ref = table[:nx, col + comp]
            if transform == "ln10":
                ref = ref * np.log(10.0)
            got = interior_profile(arr, spec, nx, comp)
            scale = max(float(np.max(np.abs(ref))), 1e-300)
            err = float(np.max(np.abs(got - ref))) / scale
            if err > worst:
                worst, worst_c = err, comp
        results.append((name, filename, worst, "ok" if worst <= rtol
                        else f"worst component {worst_c}"))
    return results


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _dims_from_args(args: argparse.Namespace) -> dict[str, int] | None:
    if getattr(args, "input", None):
        return model_dimensions(args.input)
    if getattr(args, "ncomp", None):
        return {"PRIMARY_SPECIES": args.ncomp,
                "SECONDARY_SPECIES": args.nspec or 0,
                "AQUEOUS_KINETICS": args.nkin or 0,
                "MINERALS": 0, "GASES": 0,
                "ION_EXCHANGE": 0, "SURFACE_COMPLEXATION": 0}
    return None


def _cmd_inspect(args: argparse.Namespace) -> int:
    dims = _dims_from_args(args)
    specs = infer_layout(args.file, args.nx, dims)
    buf, records = read_records(args.file)
    logger.info("%s: %d bytes, %d records, nx=%d", args.file.name, len(buf), len(specs), args.nx)
    logger.info("model dimensions: %s", dims or "not supplied (shapes may be wrong)")
    logger.info("%3s  %-18s %9s %7s  %s", "#", "record", "bytes", "elts", "layout")
    for spec, (offset, _) in zip(specs, records):
        arr = load_record(buf, offset, spec)
        flag = ""
        if spec.count and spec.dtype.kind == "f":
            flat = np.asarray(arr).ravel()
            if np.all(flat == 0):
                flag = "  [all zero]"
            elif np.ptp(flat) == 0:
                flag = f"  [constant {flat[0]:g}]"
        logger.info("%3d  %-18s %9d %7d  %s%s", spec.index, spec.name, spec.nbytes, spec.count,
                    spec.describe(), flag)
        for note in spec.notes:
            logger.info("%33s!! %s", "", note)

    (t,) = struct.unpack_from("<d", buf, records[0][0])
    (nn,) = struct.unpack_from("<i", buf, records[1][0])
    ts = struct.unpack_from("<6d", buf, records[3][0])
    logger.info("time = %g yr   nn = %d steps", t, nn)
    logger.info("delt, dtold, tstep, deltmin, dtmaxcour, dtmax = %s",
                ", ".join(f"{v:g}" for v in ts))
    ndep = sum(1 for s in specs if s.grid_dependent)
    guessed = sum(1 for s in specs if s.source == "factorisation")
    logger.info("%d of %d records grid-dependent; %d ambiguous; %d not in the declaration table",
                ndep, len(specs), sum(1 for s in specs if s.ambiguous), guessed)
    unresolved = [s.name for s in specs if s.notes and not s.grid_dependent]
    if unresolved:
        logger.warning("UNRESOLVED (regrid will refuse): %s", unresolved)
        return 1
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    dims = _dims_from_args(args)
    ok = True
    if args.identity:
        same = verify_identity(args.file, args.nx, dims)
        logger.info("identity round-trip %d -> %d: %s", args.nx, args.nx,
                    "PASS (byte identical)" if same else "FAIL")
        ok &= same
    if args.reference:
        for name, filename, err, status in verify_reference(
                args.file, args.nx, args.reference, dims, args.rtol, args.file_num):
            if err is None:
                logger.info("reference %-5s vs %-16s: SKIP (%s)", name, filename, status)
                continue
            good = err <= args.rtol
            logger.info("reference %-5s vs %-16s: %s (max rel err %.3e)", name, filename,
                        "PASS" if good else "FAIL", err)
            ok &= good
    if args.invariants:
        report = consistency_report(args.file, args.nx, dims)
        # True invariants hold in any valid restart file and gate the exit code. Start conditions
        # are what the regrid imposes so GIMRT can begin from a tiny timestep_init; CrunchTope's own
        # files legitimately violate them, having been written mid-step with two real time levels.
        invariants = {"sp10_vs_exp_sp": 1e-12}
        start_conditions = {"s_vs_sn": args.rtol, "sp_vs_spold": 0.0, "spnO2_vs_spnnO2": 0.0}
        for key, value in report.items():
            if key in invariants:
                good = value <= invariants[key]
                logger.info("invariant   %-18s: %s (%.3e, limit %.0e)", key,
                            "PASS" if good else "FAIL", value, invariants[key])
                ok &= good
            else:
                limit = start_conditions.get(key, args.rtol)
                logger.info("start-cond  %-18s: %-7s (%.3e, target %.0e)", key,
                            "met" if value <= limit else "not met", value, limit)
    for item in args.constant or []:
        name, _, raw = item.partition("=")
        want = float(raw)
        specs = {s.name: s for s in infer_layout(args.file, args.nx, dims)}
        if name not in specs or not specs[name].grid_dependent:
            logger.info("constant %s: SKIP (no such grid-dependent record)", name)
            continue
        buf, records = read_records(args.file)
        spec = specs[name]
        prof = interior_profile(load_record(buf, records[spec.index][0], spec), spec, args.nx)
        err = float(np.max(np.abs(prof - want)))
        good = err <= args.atol
        logger.info("constant %s == %g: %s (max abs err %.3e)", name, want,
                    "PASS" if good else "FAIL", err)
        ok &= good
    return 0 if ok else 1


def _cmd_regrid(args: argparse.Namespace) -> int:
    dims = _dims_from_args(args)
    inject: dict[str, np.ndarray] = {}
    if args.porosity_file:
        table = np.loadtxt(args.porosity_file)
        column = table[:, 1] if table.ndim == 2 else table
        if len(column) < args.nx_out:
            raise RstError(
                f"{args.porosity_file.name} has {len(column)} rows, need at least "
                f"nx_out={args.nx_out}"
            )
        inject["por"] = column[:args.nx_out]
    specs, rewritten = regrid(
        args.file, args.nx_in, args.nx_out, args.output, dims,
        set_dtmax=args.set_dtmax, set_dtold=args.set_dtold, set_time=args.set_time,
        allow_unresolved=args.allow_unresolved, inject=inject,
        consistent=not args.no_consistent, deck=args.input)
    for name in inject:
        logger.info("  injected %s from %s", name, args.porosity_file.name)
    if rewritten:
        logger.info("  re-derived for consistency: %s", ", ".join(rewritten))
    for key, value in consistency_report(args.output, args.nx_out, dims).items():
        logger.info("  %-18s %.3e", key, value)
    n = sum(1 for s in specs if s.grid_dependent)
    logger.info("%s (%d cells) -> %s (%d cells)", args.file.name, args.nx_in, args.output.name,
                args.nx_out)
    logger.info("  %d of %d records resampled, %d copied verbatim", n, len(specs), len(specs) - n)
    logger.info("  %d bytes", args.output.stat().st_size)
    ambiguous = [s.name for s in specs if s.ambiguous]
    if ambiguous:
        logger.warning("  ambiguous shapes: %s", ambiguous)
    if args.layout:
        args.layout.write_text(json.dumps(
            [{"index": s.index, "name": s.name, "shape": list(s.shape), "xaxis": s.xaxis,
              "pad": s.pad, "dtype": s.dtype.str, "source": s.source,
              "ambiguous": s.ambiguous} for s in specs], indent=2))
        logger.info("  layout written to %s", args.layout.name)
    return 0


def _add_dim_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--input", type=Path,
                   help="CrunchTope input deck, to count species/reaction blocks and fix the "
                        "leading axis sizes")
    p.add_argument("--ncomp", type=int, help="primary species count")
    p.add_argument("--nspec", type=int, help="secondary species count")
    p.add_argument("--nkin", type=int, help="aqueous kinetic reaction count")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="omphalos.restart_file",
        description="Inspect, validate and regrid CrunchTope restart files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__[__doc__.index("Examples"):],
    )
    sub = p.add_subparsers(dest="command", required=True)

    ins = sub.add_parser("inspect", help="dump record structure and layout")
    ins.add_argument("file", type=Path)
    ins.add_argument("--nx", type=int, required=True)
    _add_dim_args(ins)
    ins.set_defaults(func=_cmd_inspect)

    ver = sub.add_parser("verify", help="validate the inferred layout")
    ver.add_argument("file", type=Path)
    ver.add_argument("--nx", type=int, required=True)
    _add_dim_args(ver)
    ver.add_argument("--identity", action="store_true",
                     help="regrid nx->nx and require byte-identical output")
    ver.add_argument("--reference", type=Path, metavar="DIR",
                     help="directory holding the tecplot output to compare")
    ver.add_argument("--file-num", type=int, default=1,
                     help="tecplot output number the restart corresponds to; a restart is written "
                          "at the end of the run, so this is the last output, not the first")
    ver.add_argument("--constant", action="append", metavar="NAME=VALUE",
                     help="assert a record is uniform, e.g. t=4.0")
    ver.add_argument("--invariants", action="store_true",
                     help="report the state invariants a restart depends on")
    ver.add_argument("--rtol", type=float, default=1e-4)
    ver.add_argument("--atol", type=float, default=1e-9)
    ver.set_defaults(func=_cmd_verify)

    reg = sub.add_parser("regrid", help="resample onto a different nx")
    reg.add_argument("file", type=Path)
    reg.add_argument("--nx-in", type=int, required=True)
    reg.add_argument("--nx-out", type=int, required=True)
    reg.add_argument("-o", "--output", type=Path, required=True)
    _add_dim_args(reg)
    reg.add_argument("--layout", type=Path, help="also write layout JSON")
    reg.add_argument("--set-dtmax", type=float,
                     help="override stored dtmax (restart.F90 takes it from the file, not the "
                          "input deck)")
    reg.add_argument("--set-dtold", type=float, help="override stored dtold")
    reg.add_argument("--set-time", type=float, help="override stored time")
    reg.add_argument("--porosity-file", type=Path, metavar="FILE",
                     help="replace the stored porosity with this read_PorosityFile input; needed "
                          "because restart.F90 runs after StartTope and so overrides the deck")
    reg.add_argument("--no-consistent", action="store_true",
                     help="skip re-deriving sp/spold/sn/spnO2 from sp10 and s; the raw resampling "
                          "breaks the invariants GIMRT needs and Newton will fail on step 1")
    reg.add_argument("--allow-unresolved", action="store_true",
                     help="copy undecomposable records verbatim (unsafe)")
    reg.set_defaults(func=_cmd_regrid)
    return p


def main(argv: list[str] | None = None) -> int:
    """Entry point for ``python -m omphalos.restart_file``."""
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (RstError, OSError, ValueError) as exc:
        logger.error("error: %s", exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
