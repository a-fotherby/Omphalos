# MIN3P Integration Notes & Implementation Spec

Implementation plan for a `min3p/` backend in Omphalos, mirroring the existing
`omphalos/` (CrunchTope) and `pflotran/` backends.

**Status:** design resolved, implementation in progress. This document is the
single source of truth — everything verified against real files/manual is
recorded here so it need not be re-derived.

---

## 1. Environment (verified)

| Item | Path |
|------|------|
| MIN3P binary (macOS, serial) | `/Users/hjb62/MIN3P/MacOS/MIN3P-HPC-X64-V2.3.7.850-MacOS-x64` |
| MIN3P binary (macOS, OMP) | `/Users/hjb62/MIN3P/MacOS/MIN3P-HPC-X64-OMP-V2.3.7.850-MacOS-x64` |
| Benchmark examples | `/Users/hjb62/MIN3P/Examples/Benchmarks/benchmarks_standard/{batch,flow,reactran}/` |
| Thermodynamic databases | `/Users/hjb62/MIN3P/Examples/database/default/` (comp/complex/gases/mineral/redox/sorption `.dbs`) |
| User Manual (PDF, 182 pp) | `/Users/hjb62/MIN3P/User-Manual/MIN3P_THCm_UserManual.pdf` |
| Existing TecPlot reader | `/Users/hjb62/Python/MIN3P/min3pTecTools.py` |

Simplest batch benchmark for first target: `batch/appelo/appelo.dat` (kinetic
calcite dissolution, 0-D, 4 data blocks). 1-D transport example with output:
`reactran/MCD-2/min3p/` (run name `test`, produces `.gsp` output files).

---

## 2. Input file format (`.dat`) — VERIFIED against appelo.dat

- ASCII text, **CRLF** line endings. macOS `Read`/`cat` may flag as binary;
  strip `\r` when reading, emit `\r\n` when writing (or write `\n` — MIN3P on
  the parallel/HPC build tolerates LF, but preserve CRLF to be safe).
- Full-line comments start with `!` (same as CrunchTope).
- **Top-level blocks**: open with a single-quoted name on its own line, close
  with `'done'`. e.g. `'global control parameters'` ... `'done'`.
- **Within a block**: single-quoted **sub-keywords** each introduce 0+ data
  lines. Data lines are **positional** whitespace-delimited value tokens with an
  optional trailing `;comment` naming the parameter(s). Fortran conventions:
  logicals `.true.`/`.false.`, floats in d-notation `1.d-5` / `1.000E-03`.

### The central parsing problem (RESOLVED)

A single-quoted token on its own line may be **either** a structural sub-keyword
(`'components'`, `'minerals'`, `'mineral input'`) **or** a data value (the title
string, species names `'h+1'`, `'free'`, `'geometric'`). They are syntactically
identical. Disambiguation requires knowing the sub-keyword vocabulary.

**Design decision:** a *structure-preserving* parser keyed on a per-block SET of
recognised sub-keywords (`min3p/schema.py`). This is a keyword **vocabulary**,
NOT a full positional transcription of every parameter — much lighter to build
and maintainable. A quoted line is a sub-keyword iff it is in that block's
vocabulary set; otherwise it is a data line belonging to the current sub-keyword.
Data lines that appear before the first sub-keyword (e.g. the title / a leading
count) are attached to a synthetic leading key `'_header'`.

The authoritative vocabulary comes from the manual's §3 TOC (Data Blocks 1–18),
each documenting its `'sub-keyword'` grammar. See `schema.py` for the encoded set.

### appelo.dat structure (worked example)

```
'global control parameters'                    <- block name
'Dissolution of calcite ...'                    <- data (title) -> _header
.false.  ;varsat_flow                            <- data (positional booleans)
.false.  ;steady_flow
.false.  ;fully_saturated
.false.  ;reactive_transport
'done'
'geochemical system'
'use new database format'                        <- sub-keyword (no data)
'database directory'                             <- sub-keyword
'..\..\..\database\default'                      <- data (path)
'components'                                      <- sub-keyword
3                                                <- data (count)
'h+1' / 'co3-2' / 'ca+2'                          <- data (species names)
'secondary aqueous species' ...
'minerals' ...
'done'
'control parameters - local geochemistry' ...    <- Data Block 5
'initial condition - local geochemistry' ...      <- Data Block 14 (batch)
```

Note DB14 (`'initial condition - local geochemistry'`) has repeated
`'number and name of zone'` sub-keywords — multiple zones. Like CrunchTope
CONDITION/FLOW blocks, repeated sub-keywords need unique dict keys; key zones by
`{sub_keyword}#{ordinal}` or by the zone number that follows.

---

## 3. Output file format — VERIFIED against MCD-2/min3p/test_*.gsp

- TecPlot ASCII, CRLF. Run name comes from `root.dat` (single token, e.g.
  `test`, `appelo`). All output files are named `{run_name}_{N}.{ext}`.
- **Category is the file EXTENSION, timestep index `N` is the `_N` suffix.**
  This is the key difference from CrunchTope (where category is the filename
  stem and timestep is a trailing integer: `totcon1.tec`).
- Two output families (both TecPlot), VERIFIED:
  - **Spatial/transport** (`reactran/MCD-2`): `.gsp` (general spatial profile —
    primary target), `.gst`, `.gsc`, `.gsm`, `.gsa`, `.vel`, `.mac`, etc. One
    file per output **time**; `_N` = timestep index; leading columns `x,y,z`.
  - **Batch / 0-D** (live `batch/appelo` run, MIN3P v2.4.0.852): `.lbc`
    (concentrations), `.lbm` (minerals), `.lbt`, `.lbv`, `.lbd`, `.lbs`. One
    file per **zone**; `_N` = zone index; the file's rows are a **time series**
    with leading column `time` (NOT a spatial profile). `appelo_o.*` are run
    summaries (skip; `_o` is non-numeric so the `_N` glob excludes them).
  `min3p/file_methods.py` handles both: `parse_output` indexes on `x,y,z` when
  present else on `time`; `data_cats` scans `OUTPUT_EXTENSIONS` (both families).
- Header format (differs from CrunchTope uppercase `TITLE`/`VARIABLES`):
  ```
  title = "dataset test"
  variables = "x", "y", "z", "h_w", "ph_w", ...      (line 2)
  zone t = "...", i =  152, j =    1, k =    1,  f=point   (line 3)
  <whitespace-delimited float rows, Fortran E+000 3-digit exponent>
  ```
  Variable list: strip `variables = `, strip outer quotes, split on `",\s*"`
  (spacing around commas is inconsistent, e.g. `"z","h+1"`). Data rows parse as
  floats directly (`1.0E+000` is valid). First three columns are `x,y,z`.

`core/file_methods.py:parse_output()` is ~70% reusable but hard-codes `.tec`,
uppercase headers, `"\s+"` variable split, and stem-based naming — so MIN3P gets
its own `parse_output`/`data_cats` in `min3p/file_methods.py`.

---

## 4. Reuse map (verified against code)

| Component | Reuse |
|-----------|-------|
| `rhea/` (parallel exec) | Fully reusable; `rhea/main.py` dispatches backend by flag — add a `--min3p` branch mirroring `--pflotran`. |
| `core/parameter_methods.py` | Fully reusable (linspace/random_uniform/constant/custom/fix_ratio/staged). |
| `core/file_methods.py:parse_output/data_cats` | NOT directly — MIN3P naming/header differ. Write `min3p/file_methods.py`. |
| `core/file_methods.py:pickle_data_set/unpickle` | Fully reusable. |
| `core/file_methods.py:dataset_to_netcdf` | Add a `simulator='min3p'` branch (spatial category → group, concat over file_num). Model on the crunchtope branch but MIN3P categories are extensions. |
| `core/keyword_block.py:KeywordBlock` | NOT a clean fit — CT `contents[entry]` is a flat token list; MIN3P sub-keywords own MULTIPLE data lines. Use a dedicated `Min3pBlock` (see §5). |
| `min3pTecTools.py` | Reference only (readTecFile shows header handling). |

### Interfaces the backend MUST provide (so main.py/rhea/coeus work)

Mirror `omphalos/`:
- `min3p/template.py::Template(config)` — `.config`, `.keyword_blocks`,
  `.later_inputs`, `.make_dict()`, `.print()`, `.read_file()`, `.error_code`.
- `min3p/input_file.py::InputFile` — `.path`, `.keyword_blocks`, `.results`,
  `.error_code`, `.file_num`, `.print()`, `.get_results(tmp_dir)`.
- `min3p/generate_inputs.py::configure_input_files(template, tmp_dir, rhea=False, override_num=-1)`
  returning `{file_num: InputFile}`; plus `evaluate_config`, `MIN3P_IDs`.
- `min3p/run.py::run_dataset(file_dict, tmp_dir, timeout)` and `min3p(...)`.
- `min3p/main.py` — argparse entry mirroring `omphalos/main.py`.

---

## 5. Data model (`min3p/keyword_block.py`)

```python
class Min3pBlock:
    name: str                      # e.g. 'geochemical system'
    contents: dict[str, list[list[str]]]
        # key   = sub-keyword (or '_header', or 'zone#k' for repeats)
        # value = ordered list of data lines; each data line is a token list
    comments: dict[str, list[str]] # optional per-line trailing ';comment', by key
```

`modify(entry, value, line_idx, token_idx)` replaces one token; assigning a list
replaces a whole data line. `print()` re-emits: block name, then for each key in
insertion order the sub-keyword (unless `_header`) followed by its data lines
(tokens joined by whitespace, `;comment` re-appended), then `'done'`.

**Round-trip contract:** read → print → read must be *value-identical* (same
tokens per line, same order). Whitespace/column-alignment need not match byte for
byte; comments SHOULD be preserved for readability.

---

## 6. Config → input mapping (`min3p/generate_inputs.py`)

`MIN3P_IDs`: `{yaml_key: [block_name, sub_keyword_or_None, token_pos]}`. Start
with what a concentration/mineral sweep on appelo needs; extend per block.
Reuse CrunchTope YAML key names (`concentrations`, `mineral_volumes`,
`parameters`) where sensible so example configs transfer. Geochemical-condition
edits target DB14 zones; addressing by the trailing `;comment` species name is
the natural key (the files are self-documenting).

---

## 7. Module structure

```
min3p/
├── __init__.py
├── schema.py           # MIN3P_SCHEMA: per-block sub-keyword vocabulary (set)
├── keyword_block.py    # Min3pBlock data model
├── template.py         # Template(InputFile) — reads .dat
├── input_file.py       # InputFile — print() + get_results()
├── file_methods.py     # parse_output/data_cats (MIN3P TecPlot) + core re-exports
├── generate_inputs.py  # MIN3P_IDs + configure_input_files()
├── run.py              # min3p() subprocess invocation + error detection
└── main.py             # CLI entry point
```

---

## 8. Phased plan

**Phase 1 — MVP: COMPLETE.** batch/appelo end-to-end, verified.
1. [done] skeleton + `schema.py` (DB1,2,5,14 vocab).
2. [done] `keyword_block.py` + `template.py` + `input_file.py`. Round-trip is
   value-identical on **all 87 genuine MIN3P input `.dat` files** in the
   benchmark suite (the 28 non-round-tripping `.dat` files are TecPlot output,
   thermodynamic-database, and PHREEQC files, correctly rejected).
3. [done] `file_methods.py` MIN3P `parse_output`/`data_cats` (spatial + batch);
   `get_results` concatenates over an `output` index.
4. [done] `run.py` subprocess + `root.dat` write + error detection.
5. [done] `generate_inputs.py` + `MIN3P_IDs` alias table + explicit
   `modifications` scheme + `database_directory` repointing.
6. [done] `min3p/main.py` CLI; `example_min3p.yaml`.
7. [done] 27 unit tests in `tests/unit/test_min3p.py` (all pass; full suite
   213 passed in the `omphalos` env). Live 3-file calcite-volume sweep of
   appelo run through the real binary (v2.4.0.852): all `error_code=0`, results
   parsed to xarray.

Remaining Phase-1 polish (not blocking): `dataset_to_netcdf` min3p branch and
`rhea/main.py --min3p` flag for parallel execution + netCDF packaging.

**Phase 2 — transport (later):** add DB3 (spatial discretization), DB4 (time
step control), DB7/11 (reactive transport params), DB15/16 (RT initial/boundary
conditions) to schema; validate on `reactran/MCD-2`. Wire `dataset_to_netcdf`
min3p branch and `rhea/main.py --min3p`.

**Phase 3 — full coverage:** flow (DB6/9/10/12/13), energy balance, restart
chains.

---

## 9. Manual reference (page = internal 3-XX ≈ PDF page in §3)

Data Blocks in `MIN3P_THCm_UserManual.pdf` §3: DB1 global control, DB2
geochemical system (~pp.30–47), DB3 spatial discretization (3-49), DB4 time step
control (3-51), DB5 control params–local chem (3-53), DB6 control params–flow
(3-56), DB7 control params–RT (3-78), DB8 output control (3-88), DB9/10/11
physical params (3-91/95/104), DB12/13 IC/BC flow (3-111/116), DB14 IC batch
(3-124), DB15 IC RT (3-139), DB16 BC RT (3-147). Use `pdftotext -f P -l P` to
read specific pages.

---

## 10. Current status (2026-07-24)

### Consolidated summary

| Capability | Status |
|------------|--------|
| `.dat` parse + value-identical round-trip | ✅ 363/365 whole example corpus (0 mismatches; rest are non-inputs) |
| Block-type coverage | ✅ 0 unknown block openers across the whole corpus |
| Positional modification (block/keyword/line/token) | ✅ |
| Sequential sweep → `results.nc` (`min3p.main`) | ✅ |
| Parallel-local sweep (`rhea ... -m`) | ✅ |
| Batch 0-D kinetics | ✅ end-to-end (appelo) |
| 1-D reactive transport (diffusion) | ✅ end-to-end (MCD-2) |
| 1-D advective-dispersive flow + `.vel` | ✅ end-to-end (MCD-2-advection) |
| Heat transport (energy balance, `temp_n`) | ✅ end-to-end (radial-flow) |
| Restart chains (multi-stage continuation) | ✅ end-to-end (MCD-2, 2-stage) |
| rhea cluster/sbatch mode | ❌ TODO (untestable here) |

Output categories parsed (23), in three families:
- spatial `gs*` + `vel` (x,y,z per output time): `gsp` flow, `gsc` concs,
  `gsm` master/pH, `gst` totals, `gsv` volumes+porosity, `gss` sat. indices,
  `gsd` reaction rates, `gsx` excluded-mineral SI, `vel` Darcy velocity;
- breakthrough `gb*` (time series per observation point): `gbc gbm gbt gbv gbs
  gbd gbx`;
- batch `lb*` (time series per zone): `lbc lbm lbt lbv lbs lbd lbx`.
Not parsed by design: per-component/mineral mass-balance diagnostics
`.mac`/`.mae`/`.mmc`, two-index per-species flux `.gsa`, and `_o.*` summaries
(they use component/mineral indexing, not space or time).
Test suite: **238 passed** (52 MIN3P) in the `omphalos` conda env.

Worked example: `min3p/examples/dissol_sweep/` — a 4-run inflow-acidity sweep on
`reactran/dissol` with a notebook (`dissol_sweep.ipynb`) that reads `results.nc`
and plots the dissolution front (Ca²⁺, pH, calcite volume fraction vs depth).

### 2026-07-24 — completeness audit (whole example corpus)

A corpus-wide audit (parse every `.dat`, compare block openers to the schema,
flag mis-grouped multi-word lines) surfaced and fixed:

- **Parser robustness (correctness fix in `template.py`):** the opener rule was
  too permissive — an un-commented banner (`Data Block 16: ...` missing its
  `!`), a stray double-quoted title, or an orphan `'done'` could be mistaken for
  a block opener, which *swallowed the real block that followed*. Now a line
  opens a block only if its first token is a lone single-quoted keyword and not
  `'done'`; everything else outside a block is passthrough. This fixed real RT
  boundary blocks in ~14 files (e.g. `basin.dat`) that had silently failed to
  register. Round-trip corpus coverage rose 319 → 363 (0 mismatches).
- **En-dash block names (`normalise` in `keyword_block.py`):** some files spell
  the separator with an en-dash (`control parameters – variably saturated
  flow`); en-/em-dashes now fold to a hyphen so they match the schema.
- **Schema completeness (`schema.py`):** added the remaining block types — DB17
  ice-sheet, DB18 plant-transpiration, evaporation, bubble-model, and a
  `control parameters - water flow` alias — plus missing sub-keywords: DB2
  (`non-aqueous components`, `sorbed species`, `redox couples`, intra-aqueous
  kinetics), DB3 (structured/USG grid keywords), DB6 (`compute underrelaxation
  factor`), DB7 (`harmonic average in porosity`), DB15/16 (`guess for ph`,
  ion-exchange/sorption inputs, transient read-time markers). Result: **0
  unknown block openers** corpus-wide; remaining unrecognised lines are all
  legitimate data (titles, zone/material names, unit values).
- `vocab_for()` now normalises its argument defensively.
- 3 regression tests added (banner-not-a-block, orphan-`done`, en-dash match). Shared-file edits are all additive/guarded; CrunchTope and
PFLOTRAN paths untouched.

---

**Phase 1 MVP: COMPLETE and verified.** Sequential batch sweeps run end-to-end.

Delivered (all additive — no existing backend modified):
- `min3p/` package: `__init__`, `schema`, `keyword_block`, `template`,
  `input_file`, `file_methods`, `generate_inputs`, `run`, `main`.
- `example_min3p.yaml`; `tests/unit/test_min3p.py` (27 tests).
- Round-trip: value-identical on all 87 genuine benchmark input files.
- Live run: 3-file appelo calcite-volume sweep via real binary (v2.4.0.852),
  all `error_code=0`, results parsed to xarray.
- Full suite: **213 passed** in the `omphalos` conda env (NOT JupyterEnv, which
  lacks `f90nml`).

Environment notes:
- Run/test with `conda run -n omphalos python -m pytest -q`.
- MIN3P success is detected by the `normal exit` banner in stdout (see
  `run.MIN3P_SUCCESS_MARKER`), not by scanning for the word "error".
- Benchmark `.dat` files use a Windows `database directory` path; set
  `database_directory` in the config to repoint it (done automatically by
  `generate_inputs`).

**Phase-1 polish (parallel + netCDF): COMPLETE (local mode).**
1. [done] `core/file_methods.dataset_to_netcdf` — `simulator='min3p'` branch:
   concatenates each category over `file_num`, converts adaptive batch `time`
   to a positional `step` dim (keeping real times as a `(file_num, step)`
   coord, so ragged runs pad with NaN rather than misalign), sanitises `/` in
   variable names. Wired into `min3p/main.py`. 2 unit tests.
3. [done] `rhea` `--min3p` flag: `rhea/main.py` (isolated local-mode branch that
   bypasses `prep_directories.sh`), `rhea/slurm_exec.py` (MIN3P `execute`
   branch), `rhea/slurm_interface.compile_results(simulator=...)`. Verified
   end-to-end: `python rhea/main.py cfg.yaml local -m --backend xargs` on appelo
   → 3 parallel runs, 0 failures, `results.nc` identical to sequential.
   All shared-file edits are additive/guarded; full suite 215 passed.

**TODO — rhea cluster mode for MIN3P:** the sbatch path (`--min3p` +
`run_type cluster`) is not yet implemented (currently errors out); it needs a
MIN3P-aware `prep_directories.sh`/sbatch that skips the CT database-file copy.
Untestable without a cluster here.

**Next (Phase 2 — transport):** extend `schema.py` with DB3/DB4/DB7/DB11/
DB15/DB16 sub-keyword vocabularies; validate round-trip + a sweep on
`reactran/MCD-2` (1-D, `.gsp` spatial output).

---

## 11. Progress log

**2026-07-24 — Phase 1 + polish delivered (this session).**

Files added (new, isolated): `min3p/` package (`__init__`, `schema`,
`keyword_block`, `template`, `input_file`, `file_methods`, `generate_inputs`,
`run`, `main`), `example_min3p.yaml`, `tests/unit/test_min3p.py` (29 tests).

Files touched (shared; every edit additive/guarded, existing backends
unaffected — verified by 215-green suite):
- `core/file_methods.py` — added `simulator='min3p'` branch to
  `dataset_to_netcdf` (positional `step` concat for ragged batch time axes,
  `/`-sanitising, per-category netCDF groups).
- `rhea/main.py` — added `-m/--min3p`; isolated local-mode branch bypassing
  `prep_directories.sh`.
- `rhea/slurm_exec.py` — added MIN3P `execute` branch + `-m` flag.
- `rhea/slurm_interface.py` — `compile_results(simulator=...)`; switched its
  `fm` import to `core.file_methods` (behaviourally identical re-export).
- `README.md` — `-m` flag, MIN3P Support section, `min3p/` in structure, test
  count 152→215.

Verified: round-trip value-identical on all 87 genuine benchmark `.dat` files;
live sequential AND rhea-local parallel sweeps of `batch/appelo` via the real
binary (v2.4.0.852) → 0 failures, `results.nc` written, identical Ca²⁺ finals
both ways.

Environment: run/test with `conda run -n omphalos ...` (NOT JupyterEnv).

**2026-07-24 — Phase 2 (transport): COMPLETE.** Validated on `reactran/MCD-2`
(1-D NaClHNO3 multicomponent diffusion).

- `min3p/schema.py` extended with DB3 (spatial discretization), DB4 (time step
  control), DB6/7 (control params flow/RT), DB8 (output control), DB9/10/11
  (physical params), DB12/13 (IC/BC flow), DB15/16 (IC/BC reactive transport),
  plus the `'potential reference coordinates'` block and DB1 process flags
  (`'multicomponent diffusion'` etc.). Block-name spelling follows the files
  (`variably saturated`), with alias keys bridging the manual's
  `variably-saturated`. Grouping verified: RT `'concentration input'` resolves
  per component, and repeated boundary zones disambiguate to
  `concentration input` / `concentration input#2`.
- `min3p/file_methods.py`: `SPATIAL_EXTENSIONS` now `('gsp','gsc','gsm')` — the
  spatial family splits across `.gsp` (flow vars), `.gsc` (component
  concentrations), `.gsm` (pH/ionic strength/alkalinity). (`.gsa` per-species
  detail uses a two-index `test_N_M` name and is not parsed.)
- Round-trip still value-identical on all 87 genuine benchmark files.
- Live 3-file sweep of MCD-2 inflow-boundary pH = {3,4,5} via the real binary:
  h+1 at the inflow node = {1e-3, 1e-4, 1e-5} exactly, in `.gsc` (dims
  file_num=3, output=9, x=152); `results.nc` written with groups gsp/gsc/gsm.
- 6 Phase-2 unit tests added; full suite **221 passed**.

**2026-07-24 — Phase 3 (advective flow): STARTED — advection COMPLETE.**
Validated on `reactran/MCD-2-advection` (1-D advective-dispersive transport).

- Advection reuses the Phase 2 block set (no new blocks); flow is enabled purely
  by parameter values — hydraulic conductivity (`physical parameters - variably
  saturated flow` → `hydraulic conductivity in {x,y,z}-direction`) and boundary
  head (`boundary conditions - variably saturated flow` → `boundary type` /
  `boundary type#2`, token 1). Both confirmed addressable via the schema.
- `min3p/file_methods.py`: added `vel` to `SPATIAL_EXTENSIONS` — the Darcy
  velocity field (`vx,vy,vz`) on cell faces (one fewer node; own netCDF group,
  no coord conflict). Steady flow writes a single output index.
- Live 3-file sweep of outflow head = {0.99, 0.95, 0.90} via the real binary:
  max|vx| = {4.32e-4, 2.16e-3, 4.32e-3} m/s — exactly 1x/5x/10x the head
  gradient, i.e. Darcy's law v = K·dh/dx holds. `results.nc` groups
  gsp/gsc/gsm/vel written.
- 4 Phase-3 unit tests added; round-trip still 87/87; full suite **225 passed**.

**2026-07-24 — Phase 3 (energy balance / heat transport): COMPLETE.**
Validated on `nwmo_verification_examples_D4/d41_radial_flow_energy` (radial
density-dependent flow with heat transport).

- `min3p/schema.py` extended with the energy stack: DB1 flags (`energy balance`,
  `density dependent flow`), DB6b (`control parameters - energy balance`), DB10b
  (`physical parameters - energy balance` — specific heats, water/solid thermal
  conductivity x/y/z, dispersivities), DB12b (`initial condition - energy
  balance`), DB13b (`boundary conditions - energy balance`). Also added DB2
  `excluded minerals`, DB3 `radial coordinates`, and DB6 density/solver options
  (`variable density parameters`, `iterative solver`, etc.).
- Temperature output is the `temp_n` variable in `.gsp` — already captured by
  the existing spatial parser; no new extension needed.
- Broad round-trip across the WHOLE example corpus: **319/390 `.dat` files
  value-identical, 0 mismatches** (the 71 non-round-tripping files are TecPlot
  analytical-output and numeric `restart.dat` dumps, correctly rejected).
- Live 3-file inflow-temperature sweep = {0.5, 1.0, 2.0} via the real binary:
  `temp_n` at the inflow node = {0.500, 1.000, 2.000} exactly. `results.nc`
  groups gsp/gsc/gst/vel written.
  NB: the shipped energy benchmarks carry a defect (`'extent of zone'Potranco`
  and hardcoded Windows DB paths) that MIN3P's own reader rejects; Omphalos
  round-trips them faithfully regardless, and the live run used a one-character
  repair of the *benchmark* (not Omphalos) to exercise the pipeline.
- 4 energy unit tests added; full suite **229 passed**.

**Coverage:** batch 0-D, 1-D diffusion, 1-D advective flow, and heat transport
all work end-to-end (sequential + parallel-local).

**2026-07-24 — Phase 3 (restart chains): COMPLETE.** Validated on a 2-stage
MCD-2 chain (t: 0->100->200).

- MIN3P restart mechanism (User Manual DB1): a run writes rolling `restart.tmp1`
  (Nt steps) / `restart.tmp2` (2*Nt steps) state files; enabling `'restart'` in
  global control makes the next run continue from `restart.dat` (the latest temp
  file, renamed). `'append results'` resumes transient output at the break point.
- `min3p/keyword_block.py`: `Min3pBlock.add_keyword()` injects a sub-keyword
  (e.g. `'restart'`, `'append results'`) before `'done'` and re-groups; the
  block now stores its `vocab` so it can regroup. `schema.py`: restart
  directives added to global-control vocab.
- `min3p/generate_inputs.py`: `configure_staged_input_files()` returns
  `{run: {stage: InputFile}}`; stage 0 is the base (+ any `modifications`), later
  stages add `'restart'`/`'append results'` and set their own final solution
  time (default coord = time-step-control `_header` line 2, overridable).
- `min3p/run.py`: `run_staged()` runs stages sequentially in one dir, cleaning
  stale restart files at stage 0 and promoting the latest `restart.tmp` to
  `restart.dat` between stages (picks the temp file with the greater recorded
  time). `min3p/main.py` dispatches to the staged path when `restart_chain` is
  set, using a per-run subdirectory so runs don't collide.
- Live 2-run x 2-stage MCD-2 chain via the real binary: every stage normal exit,
  both runs' `restart.tmp2` reach t=200, `results.nc` written (gsp/gsc/gsm/vel).
- 5 restart unit tests; `example_min3p_restart.yaml` added; full suite
  **234 passed**.

**2026-07-24 — output coverage expanded + worked reactive-transport example.**

*Output coverage (`min3p/file_methods.py`).* A full inventory of a reactive-
transport run showed MIN3P emits three field-output families; the parser now
captures all 23 categories (previously ~10):
- SPATIAL `gs*` + `vel` (leading x,y,z; one file per output time): `gsp` flow,
  `gsc` concs, `gsm` master/pH/alkalinity, `gst` totals, `gsv` volume fractions
  + porosity, `gss` sat. indices, `gsd` dissolution-precipitation rates, `gsx`
  excluded-mineral SI, `vel` Darcy velocity. (Added `gst`/`gsd`/`gsx`.)
- BREAKTHROUGH `gb*` (leading `time`; one file per observation point):
  `gbc gbm gbt gbv gbs gbd gbx` — a whole family that had been missing.
- BATCH `lb*` (leading `time`; one file per zone): `lbc lbm lbt lbv lbs lbd lbx`
  (added `lbx`).
- `parse_output` already auto-detects x,y,z vs `time`; `data_cats`/`get_results`
  iterate `OUTPUT_EXTENSIONS`, so only the extension lists changed.
- Intentionally NOT parsed (documented in the module): per-component/mineral
  mass-balance diagnostics `.mac`/`.mae`/`.mmc` (leading `time [days]`, indexed
  by component/mineral), the two-index per-species flux detail `.gsa`
  (`run_N_M.gsa`), and the `_o.*` run summaries.
- 2 tests added (breakthrough parsing; `data_cats` across all families).

*Worked example (`min3p/examples/dissol_sweep/`).* End-to-end demonstration on
`reactran/dissol` (1-D calcite dissolution during transport):
- `dissol_sweep.yaml` — 4-run sweep over inflow acidity (free H+ at the inflow
  boundary, 0.25x-2x default) via the `modifications` scheme.
- Ran through the real binary → `results.nc` (all groups) + `records.pkl`.
- `dissol_sweep.ipynb` — reads `results.nc` and plots the dissolution front
  (Ca2+, pH, calcite volume fraction vs distance) using the publication style
  sheet; executed with nbconvert (0 errors, outputs embedded). Kernel is
  `JupyterEnv` (has the Jupyter stack); the notebook only reads `results.nc`, so
  it has no dependency on the `min3p` package. `dissol_sweep.png` + `README.md`
  included.
- Result: mild inflow waters stay calcite-buffered (pH ~8-10, calcite intact);
  the two aggressive waters exhaust calcite near the inlet (volfrac -> 1e-7) and
  the acid front breaks through (pH 4.95 / 1.75) — a textbook RTM sweep.
- Full suite **238 passed** (52 MIN3P).

**Next (Phase 3 cont.):** rhea cluster-mode MIN3P support (the only remaining
roadmap item; `--min3p` + `run_type cluster` currently errors out, and sbatch
is untestable without a cluster).
