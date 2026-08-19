# Omphalos

<p align="center">
  <strong>A powerful automation tool for designing and running geochemical modelling experiments</strong>
</p>

<p align="center">
  <a href="#features">Features</a> •
  <a href="#installation">Installation</a> •
  <a href="#quick-start">Quick Start</a> •
  <a href="#configuration-guide">Configuration</a> •
  <a href="#citation">Citation</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/tests-1079%20passed-brightgreen" alt="Tests">
  <img src="https://img.shields.io/badge/python-3.8%2B-blue" alt="Python">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="License">
  <img src="https://img.shields.io/badge/CrunchTope-supported-orange" alt="CrunchTope">
  <img src="https://img.shields.io/badge/PFLOTRAN-supported-orange" alt="PFLOTRAN">
  <img src="https://img.shields.io/badge/MIN3P-supported-orange" alt="MIN3P">
</p>

---

## Features

- **Simplify geochemical modelling** — Automate parameter sweeps and sensitivity analyses
- **Test thousands of combinations** — Generate and run hundreds to thousands of simulations effortlessly
- **Parallel execution** — Run simulations locally or on SLURM-managed clusters
- **Multiple simulators** — Support for CrunchTope, PFLOTRAN, and MIN3P-THCm
- **Unified results** — Collate all outputs into structured xarray/netCDF datasets
- **Flexible configuration** — YAML-based configuration for easy parameter specification

---

## Table of Contents

- [Installation](#installation)
  - [Linux/Mac](#linuxmac)
  - [Windows](#windows)
  - [Development Setup](#development-setup)
- [Quick Start](#quick-start)
  - [Example Configuration](#example-configuration)
  - [Run Your First Simulation](#run-your-first-simulation)
- [Usage](#usage)
  - [Running Simulations](#running-simulations)
  - [Collecting Results](#collecting-results)
- [Configuration Guide](#configuration-guide)
  - [Frontmatter](#frontmatter)
  - [Parameter Modification](#parameter-modification)
    - [Keyword Blocks](#keyword-blocks)
    - [Condition Blocks](#condition-blocks)
    - [Namelists](#namelists)
    - [Database Parameters](#database-parameters)
    - [Adding an isotope](#adding-an-isotope)
    - [Recomputing log K with pyGCC](#recomputing-log-k-with-pygcc)
    - [Adding species a database lacks](#adding-species-a-database-lacks)
    - [Changing the temperature points](#changing-the-temperature-points)
  - [Modification Options](#modification-options)
  - [Staged Restarts](#staged-restarts)
- [Project Structure](#project-structure)
- [Testing](#testing)
  - [Test Categories](#test-categories)
- [Analysis with Coeus](#analysis-with-coeus)
  - [Loading and Filtering Results](#loading-and-filtering-results)
  - [Attribute Tables](#attribute-tables)
  - [Recovering Failed Runs](#recovering-failed-runs)
  - [Collating PFLOTRAN Results](#collating-pflotran-results)
  - [Compiling Input Conditions](#compiling-input-conditions)
  - [Plotting Utilities](#plotting-utilities)
  - [Example Notebooks](#example-notebooks)
  - [Worked Examples](#worked-examples)
- [Advanced Topics](#advanced-topics)
  - [Non-Unique Entries](#non-unique-entries)
  - [Line Continuation](#line-continuation)
  - [Pump Keyword in FLOW Block](#pump-keyword-in-flow-block)
  - [Choosing a Parallelization Backend](#choosing-a-parallelization-backend)
  - [Cluster Runs](#cluster-runs)
  - [Inspecting a Restart File](#inspecting-a-restart-file)
  - [Keep the Working Directory Path Short](#keep-the-working-directory-path-short)
  - [Two-Dimensional Decks](#two-dimensional-decks)
  - [PFLOTRAN Support](#pflotran-support)
  - [MIN3P Support](#min3p-support)
- [Citation](#citation)
- [License](#license)

---

## Installation

### Linux/Mac

```bash
# 1. Clone the repository
git clone https://github.com/a-fotherby/Omphalos.git
cd Omphalos

# 2. Run the installation script
./install.sh

# 3. Activate the environment
conda activate omphalos
```

> **Note:** Provide the *absolute path* to your CrunchTope executable during installation. You can modify it later in `omphalos/settings.py`.

### Windows

> **Status:** Untested

```powershell
# Run PowerShell as Administrator
Set-ExecutionPolicy Bypass -Scope Process -Force
./install.ps1

# Activate the environment
conda activate omphalos
```

### Development Setup

For development with testing capabilities:

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -e ".[dev]"

# Run tests
pytest tests/ -v
```

#### Git Hooks

`install.sh` (and `install.ps1`) point git at the tracked hooks in `.githooks/`. To enable them in an
existing checkout:

```bash
git config core.hooksPath .githooks
```

The one hook is a `pre-commit` that keeps the test counts quoted in this README — the badge and the
line above the Test Categories table — in step with the number of tests pytest collects. It runs only
when a commit touches `tests/`, `README.md` or `pyproject.toml`, and it never blocks a commit: if it
cannot find an interpreter with pytest, or the README has unstaged changes it would have to disturb,
it says so and gets out of the way. It also warns about test modules missing from the table.

Run it by hand at any time:

```bash
python .githooks/update_test_counts.py
```

---

## Quick Start

Omphalos requires two inputs:

1. **A working CrunchTope, PFLOTRAN or MIN3P model** — Your template input file
2. **A YAML configuration file** — Specifies how to vary model parameters

> **Note:** Your CrunchTope template must have `graphics tecplot` in the RUNTIME block. Omphalos parses the TecPlot output format.

### Example Configuration

```yaml
# config.yaml
template: 'my_model.in'
database: 'thermodynamic.dbs'
timeout: 300
conditions: ['seawater', 'sediment']
number_of_files: 100
nodes: 4

# Vary sulfate concentration linearly from 1 to 30 mM
concentrations:
  seawater:
    SO4--:
      - 'linspace'
      - [1, 30, 1]

# Vary mineral dissolution rate randomly
mineral_rates:
  Calcite&default:
    - 'random_uniform'
    - [1e-12, 1e-10]
```

> **Note:** Omphalos must be run from the directory containing your template input file and config YAML. Output files (`results.nc`, `inputs.pkl`, and the `run*/` working directories) are written to the current working directory.

### Run Your First Simulation

```bash
# Sequential execution (simple simulations)
python -m omphalos.main config.yaml output.pkl

# Parallel execution (recommended for most use cases)
python -m rhea.main config.yaml local

# Or on a SLURM cluster
python -m rhea.main config.yaml cluster
```

---

## Usage

### Running Simulations

| Command | Description | Use Case |
|---------|-------------|----------|
| `omphalos config.yaml output.pkl` | Sequential execution | Simple simulations, debugging |
| `rhea config.yaml local` | Parallel local execution | Multi-core workstations |
| `rhea config.yaml cluster` | SLURM cluster execution | HPC environments |

**Flags:**
- `-p, --pflotran` — Use PFLOTRAN instead of CrunchTope
- `-m, --min3p` — Use MIN3P instead of CrunchTope (see [MIN3P Support](#min3p-support))
- `-d, --debug` — Generate files without running simulations. `omphalos` writes them to `tmp/` as
  `<template><N>.<ext>` (e.g. `tmp/model0.in`); `rhea` writes them into the prepared `run<N>/` directories
- `-c, --compile-inputs` — After a local CrunchTope or MIN3P run, also record the parameter values the sweep
  used, named to pair with the results file just written (see [Compiling Input Conditions](#compiling-input-conditions))
- `-b, --backend` — Parallelization backend: `xargs` (default) or `parallel` (GNU Parallel)

> **`rhea` empties a run directory before reusing it.** The stale deck, database, `.tec` or MIN3P
> output and `.rst` restart all go, because both solvers write output per snapshot and a run producing
> fewer snapshots than last time would otherwise leave the surplus behind to be collated as its own. The
> per-run `input_file<N>_complete.pkl` is kept, and nothing outside the run directories is touched, so
> an earlier `results.nc` and `conditions.nc` survive.
>
> Directories left by a **larger** sweep are refused rather than cleared: rerunning a three-run config
> where `run0`–`run7` exist stops with an error naming `run3`–`run7`, before anything is removed.
> Clearing them would throw away a record; ignoring them would let `coeus` compile eight runs'
> parameters beside three runs' results, joined silently on run number. Move them aside, or run the
> smaller sweep elsewhere.

### Collecting Results

Results are saved in two formats:

#### 1. NetCDF Results (`results.nc`)

```python
import xarray as xr

# Load mineral volume data
volumes = xr.open_dataset('results.nc', group='volume')

# Load total concentration data
concentrations = xr.open_dataset('results.nc', group='totcon')

# Access dimensions: X, Y, Z, time, file_num
print(volumes.dims)
```

`file_num` is labelled with the run numbers that compiled successfully, so a sweep with failed or timed-out runs
produces fewer slices than `number_of_files` and the labels tell you which runs survived. Select by run number
with `.sel(file_num=...)`, and join against `conditions.nc` on the same coordinate rather than by position.

> **Variable names come from CrunchTope's tecplot headers, inconsistencies included.** The `velocity` group holds
> `X Velocity` with a space but `Y-Velocity` and `Z-Velocity` with hyphens. They are passed through as written so
> that `results.nc` matches the `.tec` files it was built from, so index them by their exact names.

**Sweeps run in the same directory are numbered, not overwritten.** A second sweep writes `results1.nc`, a third
`results2.nc`, and so on. The parameter record written by `--compile-inputs` takes its name from the results file
it belongs to, so the pairs stay together:

| Sweep | Results | Parameter record |
|-------|---------|------------------|
| 1st | `results.nc` | `conditions.nc` |
| 2nd | `results1.nc` | `conditions1.nc` |
| 3rd | `results2.nc` | `conditions2.nc` |

Always read a pair with matching suffixes. Mixing them — one sweep's results with another's parameters — joins
without complaint, since both are indexed by run number.

Available groups depend on your CrunchTope OUTPUT block configuration. Common groups include:
- `totcon` — Total concentrations
- `volume` — Mineral volumes
- `rate` — Reaction rates
- `pH` — Solution pH
- `saturation` — Mineral saturation indices

#### 2. Input File Record (`inputs.pkl`)

```python
from omphalos.file_methods import unpickle

# Load the input file dictionary
input_files = unpickle('inputs.pkl')

# Access a specific input file
input_file = input_files[0]

# Reconstruct the original text file
input_file.print()
```

#### 3. Failed Runs

A run can fail in two ways, and `rhea` reports them separately when it compiles the sweep:

```
Files compiled: 8 of 10.
Files that returned no output (1): [4]
Files that failed during the run (1), as run: error_code: {7: 1}
```

- **Returned no output** — no `run<N>/input_file<N>_complete.pkl` to read, so the worker died before it could
  record anything.
- **Failed during the run** — the run came back carrying a non-zero `error_code`: `1` is a timeout, higher
  values are the error patterns in `omphalos/run.py` (`CT_ERROR_PATTERNS`) matched in CrunchTope's output, such as
  a convergence failure or a missing input file, and `-1` means CrunchTope exited cleanly without writing any
  tecplot output. That last one catches the many fatal paths that print a message and simply stop: an exit is
  indistinguishable from a clean finish, so such runs used to be recorded as successes. Decks that legitimately
  write no snapshots — `speciate_only`, or no `spatial_profile` — are exempt.

Neither kind contributes data, so both are left out of `results.nc`. If no run returns usable output, no results
file is written at all and `rhea` exits non-zero:

```
WARNING: no run returned usable output, so no results file was written.
Files compiled: 0 of 10.
```

Failures need not stop the analysis: `results.nc` is labelled by run number, so it joins onto `conditions.nc`
correctly with the failures simply absent.

Collation reads one run at a time and spills its parsed output to a temporary netCDF file, so memory is bounded by
one run plus the single output category being written rather than by the whole sweep. The results are therefore
written to disk twice; set `TMPDIR` to somewhere with room if the default temporary directory is small or under
quota. Use `coeus.helper.filter_errors` for the same accounting on the
sequential (`omphalos`) path, and `coeus/retrieval_run.py` to salvage output from run directories after an
interrupted sweep.

---

## Configuration Guide

Fully annotated reference configs live beside the backend they drive:
[`omphalos/example.yaml`](omphalos/example.yaml) for CrunchTope, and
[`min3p/example_min3p.yaml`](min3p/example_min3p.yaml),
[`min3p/example_min3p_transport.yaml`](min3p/example_min3p_transport.yaml) and
[`min3p/example_min3p_restart.yaml`](min3p/example_min3p_restart.yaml) for MIN3P. They document the schema rather
than being runnable: for sweeps you can run, see [Worked Examples](#worked-examples).

### Frontmatter

| Keyword | Description | Required | Example |
|---------|-------------|----------|---------|
| `template` | Path to template input file | Yes | `'model.in'` |
| `database` | Path to thermodynamic database | Yes | `'database.dbs'` |
| `aqueous_database` | Path to aqueous database | No | `'aqueous.dbs'` |
| `catabolic_pathways` | Path to catabolic pathways | No | `'CatabolicPathways.in'` |
| `restart_file` | Existing restart file to copy to all runs | No | `'spinup.rst'` |
| `timeout` | Max simulation time (seconds); if exceeded, the run is killed and excluded from `results.nc` | Yes | `300` |
| `conditions` | Names of the geochemical conditions (matching your CrunchTope CONDITION blocks) that parameter modifications may target | Yes | `['boundary', 'initial']` |
| `number_of_files` | Number of simulations | Yes | `100` |
| `nodes` | Parallel workers/SLURM nodes | Yes | `4` |

> **Spatial data files need no frontmatter entry.** Any file your template names with a `read_*file`
> keyword — `read_PorosityFile`, `read_temperaturefile`, `read_TortuosityFile`, `read_permfile`,
> `read_saturationfile` and the rest — is found by reading the template and copied into every run
> directory alongside the databases. Relative paths are preserved, so `data/porosity.dat` lands in a
> `data` subdirectory of the run; absolute paths are left alone, since they resolve from anywhere.
> The filename is the *first* token of the keyword: anything after it is a format specifier, as in
> `read_PorosityFile porosity.dat FullForm`.

> **An `aqueous_database` or `catabolic_pathways` entry must be named in the deck's RUNTIME block**,
> in the spelling your CrunchTope reads — `kinetic_database`/`catabolic_database` for 1.x,
> `aqueousdatabase`/`catabolicdatabase` for 2+. Omphalos writes the file under whatever name RUNTIME
> gives, checks the spelling against the executable before each sweep, and refuses to run on a
> mismatch: CrunchTope ignores a keyword it does not recognise and completes the run without the
> database, which is not a failure you would notice in the output.
>
> **`AqueousControl.ant` and `CatabolicControl.ant` are not supported.** Some builds take the
> filename from those instead, which is how a few of the short-course exercises are set up — they
> work under CrunchTope with no RUNTIME keyword at all. Omphalos has nothing to write to in that
> case, so add the keyword to the deck; the `.ant` files are then unnecessary. Rare, but it is why an
> exercise deck may need that one line added before a sweep will start.

### Parameter Modification

#### Keyword Blocks

Modify parameters in standard CrunchTope blocks:

| CrunchTope Block | Config Keyword |
|------------------|----------------|
| `RUNTIME` | `runtime` |
| `OUTPUT` | `output` |
| `TRANSPORT` | `transport` |
| `FLOW` | `flow` |
| `MINERALS` | `mineral_rates` |
| `AQUEOUS_KINETICS` | `aqueous_kinetics` |
| `ISOTOPES` | `isotopes` |
| `EROSION/BURIAL` | `erosion/burial` |
| `BOUNDARY_CONDITIONS` | `boundary_conditions` |

> **Note:** `boundary_conditions` varies the *condition* a boundary draws from, not the boundary
> type — `x_begin: ['custom', ['boundary', 'initial']]` turns `x_begin boundary flux` into
> `x_begin initial flux`, leaving `flux` alone.

> **Note:** `isotopes` entries are keyed on the **rare isotope**, since `primary` and `mineral` both
> repeat as leftmost words, and the swept value is the last token — for a mineral, its
> recrystallisation option: `Calcite44: ['custom', ['none', 'surface', 'bulk']]`. Words are recorded
> as text in `conditions.nc`, as is any non-numeric swept value.

> **Note:** Block names in your CrunchTope input file must be written in CAPITALS (e.g., `RUNTIME`, `FLOW`, `MINERALS`). The one exception is `CONDITION`, which is matched case insensitively, so `CONDITION`, `Condition` and `condition` all work. Matching the others case insensitively would mistake condition-block entries such as `temperature` for block delimiters.

> **Note:** A template need only declare the blocks its problem uses. A model with no gas chemistry can omit `GASES` entirely; absent blocks simply contribute no names when Omphalos sorts condition-block entries into minerals, gases, primary species and parameters.

```yaml
runtime:
  timestep_max:
    - 'constant'
    - 0.001

mineral_rates:
  Quartz&default:
    - 'random_uniform'
    - [1e-16, 1e-15]
```

#### Condition Blocks

Modify geochemical conditions with subcategories:

| Subcategory | Description |
|-------------|-------------|
| `concentrations` | Primary species concentrations |
| `mineral_volumes` | Mineral volume fractions |
| `mineral_ssa` | Mineral surface areas |
| `gases` | Gas partial pressures |
| `exchangers` | Cation exchange capacities, e.g. `Xna- -cec 0.001` |
| `surface_complexes` | Surface hydroxyl site densities, e.g. `>FeOH_strong 3.8e-6` |
| `parameters` | Temperature, pH, units, `SolidDensity`, etc. |

Exchangers and surface complexes are recognised by name from the `ION_EXCHANGE` and
`SURFACE_COMPLEXATION` blocks. Configs written before they had their own subcategories named them
under `parameters`; that still works.

`mineral_ssa` finds the surface area value rather than assuming its position, so it works for all of
the manual's forms — a bare trailing value, an explicit `bsa`/`ssa`/`bulk_surface_area`/
`specific_surface_area` keyword, and a secondary phase carrying a trailing nucleation threshold
(`Calcite 0.0 specific_surface_area 2.0 0.0001`, where the threshold is left alone).

```yaml
concentrations:
  seawater:
    SO4--:
      - 'linspace'
      - [1, 30, 1]
    Fe++:
      - 'constant'
      - 1e-6

mineral_volumes:
  sediment:
    Calcite:
      - 'random_uniform'
      - [0.01, 0.10]

gases:
  seawater:
    CO2(g):
      - 'linspace'
      - [1e-4, 1e-2, 1]
```

> **Note:** The `gases` keyword modifies gas partial pressures. If the gas is specified directly in a GASES block, it modifies that entry. If the gas is used to equilibrate an aqueous species (e.g., `CO2(aq) CO2(g) 0.000412`), Omphalos will find and modify the partial pressure in the concentration entry.

#### Namelists

Modify auxiliary files (aqueous database, catabolic pathways):

Three namelist groups are reachable, keyed by the file they live in:

| Config keyword | File | Namelist group | Typical use |
|---|---|---|---|
| `aqueous` | `aqueous_database` | `&Aqueous` | `keq`, the reaction's equilibrium constant |
| `aqueous_kinetics` | `aqueous_database` | `&AqueousKinetics` | `rate25C`, Monod terms, biomass, `chi` |
| `catabolic_pathways` | `catabolic_pathways` | `&CatabolicPathway` | pathway stoichiometry and yields |

```yaml
namelists:
  aqueous_kinetics:
    sulfate_reduction:
      rate:
        - 'random_uniform'
        - [1e-10, 1e-8]
  aqueous:
    Cr_Fe_redox:
      keq:
        - 'linspace'
        - [1.5, 2.5]
```

> **A rate given in the deck overrides the one in the aqueous database.** So sweeping a reaction rate
> normally means `aqueous_kinetics:` — the deck's `AQUEOUS_KINETICS` block — and not `namelists:`,
> whose `rate25C` the deck then supersedes. Use `namelists:` for what the deck cannot say: the Monod
> terms, the biomass species, `chi`, the stoichiometry.

#### Database Parameters

Modify the thermodynamic database (`.dbs`). `database:` names the file, so the parameters inside it
live under `database_parameters:`, nested section → entry → parameter:

```yaml
database_parameters:
  exchange:
    CaXRifle:
      log_k:                  # the ion-exchange selectivity coefficient
        - 'linspace'
        - [-1.2, -0.6, 1]
  mineral_kinetics:
    Calcite:                  # or 'Calcite&default'
      rate(25C):
        - 'custom'
        - [-9.0, -8.5, -8.0]
  minerals:
    Calcite:
      log_k:                  # a scalar fills every temperature point
        - 'constant'
        - 1.85
```

| Section | Editable parameters |
|---|---|
| `primary_species` | `dh_size`, `charge`, `weight` |
| `secondary_species` | `log_k`, `dh_size`, `charge`, `weight` |
| `gases`, `minerals` | `molar_volume`, `log_k`, `weight` |
| `mineral_kinetics` | `label`, `type`, `rate(25C)`, `activation`, and any other `key = value` line |
| `exchange` | `log_k`, `bfit` |
| `surface_complexation` | `log_k` |
| `surface_complexation_parameters` | `charge` |

Edits are surgical: the named token is rewritten and the rest of the file is left byte for byte as
it was. A name the database does not contain raises at generation time. Parsing happens only when a
config asks for it.

Notes:

- `log_k` is a vector over the temperature points everywhere except `exchange`, where CrunchTope
  reads a single value.
- Mineral kinetics entries are keyed `Mineral&label`. A bare `Calcite` works while only one rate law
  exists; where two parallel laws share a label they become `#1` and `#2` and a bare name raises.
- Reaction stoichiometry is not editable — changing a coefficient changes the reaction, and its
  log K would no longer belong to it.
- The in-database `aqueous_kinetics` block is deprecated and read-only; sweep aqueous kinetics
  through `namelists:` above.

#### Adding an isotope

`database_isotopes:` duplicates every species containing an element under a labelled name, with the
reaction rewritten onto the labelled parent and the log Ks copied unchanged:

```yaml
database_isotopes:
  - element: 'Ca'
    label: 44
    parents: ['Ca++']         # the primary species to label; inferred from names if omitted
    species: ['CaCO3(aq)']    # restrict the copies; their dependencies come too
    names:                    # required where no formula name can be derived
      Calcite: 'Calcite44'
    mass_shift: 4             # per atom; omitted, it is derived as label - atomic weight
    kinetics_from:            # where a copy's rate law comes from, if not its parent's
      Calcite44: 'Calcite'
    reaction_names:           # for namelist reactions the rule cannot name
      Sulfate_reduction: 'Sulfate34_reduction'
    keq_offset: -0.002        # equilibrium fractionation in the namelists, on keq
    logk_offset: -0.002       # and in the database, on the copies' log K columns
```

Each system reaches the **aqueous kinetics namelist and the catabolic pathways** as well as the
`.dbs`, since a thermodynamic isotopologue with no reactions does nothing. Reaction names take the
same formula rule — `Cr_Fe_redox` becomes `Cr53_Fe_redox` — and ones it cannot derive, like
`Sulfate_reduction`, are reported for `reaction_names`.

Affected species are found by **stoichiometry, not name** — `Calcite` and `Dolomite` contain calcium
without 'Ca' in their names — and transitively, since a reaction may stand on a secondary species
that must be labelled first.

Names are formula-aware: a symbol counts only where the next character is neither lowercase nor a
digit, so `Cl-` reads as chlorine, not carbon. Anything it cannot name unambiguously is reported
rather than guessed; supply it in `names`. A copied mineral needs a rate law or CrunchTope stops, so
the parent's kinetics block is copied where it has one and reported where it does not.

Molecular weights are shifted by default, per atom of the element, by the label minus the element's
rounded standard atomic weight — +1 for Cr53, +4 for Ca44. Set `mass_shift` to a number to override,
`null` to keep the parents' weights, or `weights` to set one outright. A species whose reaction
*consumes* the element rather than containing it — `Fe(OH)3_HS`, ferrihydrite reduced by sulfide,
written `-0.5 HS- …` — holds a negative number of atoms, which would make its copy lighter than its
parent. Those keep the parent's weight and are named in the report.

Fractionation splits by kind. **Equilibrium** fractionation is an offset on the labelled reaction's
equilibrium constant, and `keq_offset` applies it to the copied **namelist** reactions' `keq` — the
aqueous kinetics and catabolic pathways, not the `.dbs`. It is a no-op for a system with no namelist,
and for a mineral or secondary species, whose equilibrium constant is a log K column: offset those
with `logk_offset`, per atom of the element, so a species holding two sulfurs gets twice the offset.
Applied after any recomputation, which would otherwise wipe it. **Kinetic** fractionation belongs in the
input file, where the deck's `AQUEOUS_KINETICS` block sets a rate per reaction and overrides whatever
the aqueous database gives — the Sukinda deck carries `Cr_Fe_redox -rate 29.59E6` against
`Cr53_Fe_redox -rate 29.51E6`. Omphalos sweeps those through `aqueous_kinetics:`, `fix_ratio`
included, which is how a fractionation factor is swept directly: the ratio of the two rates *is*
alpha.

> **Combining this with `database_logk:`.** pyGCC holds no isotopologues, so it cannot recompute one.
> What happens instead is that a recomputation copies each parent's new column onto its copy, keeping
> the pair identical as `add_isotope` left it. Without that, pyGCC would move one side of every
> labelled pair and not the other, and the gap opening between them would be an equilibrium
> fractionation the database never had — on `SukindaCr53.dbs` at 500 bar, as much as 0.33 log units,
> which is the order of the signal an isotope model exists to measure. It is reported as
> `isotopologue row(s) copied back` in the recomputation summary, and `regrid` does the same. Worked
> example, including how large the invented fractionation would have been:
> [`omphalos/examples/isotope_pressure_series`](omphalos/examples/isotope_pressure_series/).

#### Recomputing log K with pyGCC

`database_logk:` recomputes the log K columns with [pyGCC](https://pypi.org/project/pygcc/), leaving
every other column untouched — so fitted values pyGCC cannot compute survive. With every setting
fixed it runs once, on the template, before any sweep; sweeping one moves it to once per run.

```yaml
database_logk:
  sourcedb: 'thermo.2021'
  sourceformat: 'GWB'         # GWB | EQ36 | PHREEQC | Pflotran | ToughReact
  reactions: 'all'            # or a list of species/mineral names
  on_unmatched: 'warn'        # warn | error | leave
  pressure: 500               # bar; omit for the water saturation curve
  Dielec_method: 'JN91'       # JN91 | FGL97 | DEW
  heatcap_method: 'SUPCRT'    # SUPCRT | Berman88 | HP11 | HF76
  aliases:                    # for reactions the two compilations spell differently
    Ferrihydrite: 'Fe(OH)3'
```

Expect a partial match. On `SukindaCr53.dbs`, thermo.2021 supplies 824 of 2,969 reactions; 1,985
are absent from it and 160 are written on an incompatible basis. Those keep their existing values
and are named in the report — use `on_unmatched: 'error'` where that is unacceptable.

`Dielec_method`, `heatcap_method`, `densityextrap` and `pressure` all move log K, and a `.dbs`
header has nowhere to record them, so `LogKRecalculation.settings` returns them for you to store
with the run.

Any of these settings may be given as a sweep instead of a value, which recomputes per run rather
than once. A pressure series is the usual reason:

```yaml
database_logk:
  reactions: ['Quartz']
  pressure:
    - 'custom'
    - [100.0, 250.0, 400.0, 550.0, 700.0, 850.0, 1000.0]   # bar
```

The settings each run used are written to `run*/logk_settings.json` and to the `database_logk` group
of `conditions.nc` — the only record there can be, since the database cannot carry one. Worked
example: [`omphalos/examples/quartz_pressure_series`](omphalos/examples/quartz_pressure_series/).

> **Needs `pygcc >= 1.5.3`**, which `requirements.yml` installs with pip.

#### Adding species a database lacks

`database_add:` copies species in from the source compilation, leaving everything else alone —
unlike regenerating the database, which discards the custom species and fitted values pyGCC cannot
compute.

```yaml
database_add:
  minerals: ['Anhydrite', 'Barite']
  secondary_species: ['CaSO4(aq)']
  on_unknown: 'warn'        # warn | error | leave
```

Reaction, log K, molecular weight, ion size, charge and molar volume all come from the compilation.
A species is added only where its reaction stands on species the database already has; the rest are
reported, since a row on a basis the database lacks is one CrunchTope stops reading.

#### Changing the temperature points

The usual eight points span 0–300 °C, so a low-temperature model wastes most of them.
`LogKCalculator.regrid` rewrites the database onto a grid chosen for the problem:

```yaml
database_regrid:
  temperatures: [0.0, 5.0, 10.0, 15.0, 25.0]
  reactions: 'all'          # or a list; the rest are resampled from their own curve
```

or from Python:

```python
database = Database('SukindaCr53.dbs')
LogKCalculator().regrid(database, [0.0, 5.0, 10.0, 15.0, 25.0])
database.print('SukindaCr53_cold.dbs')
```

Every row in a gridded section is rebuilt, whatever `reactions` says — rows of two widths are not a
database. Rows pyGCC cannot supply are resampled from the curve they already carry.

> **Use 1 point, or 5 to 8.** CrunchTope dimensions its arrays at compile time (`ntmp = 8`) and
> stops above that; below 5 its log K fit is underdetermined (`nbasis = 5`). One point is fine —
> isothermal is branched out and needs no fit.

Generating a database from scratch is not supported: pyGCC's CrunchTope writer is not public, and a
full regeneration would replace the fitted values this feature exists to preserve.

### Modification Options

| Option | Description | Syntax |
|--------|-------------|--------|
| `linspace` | Linear spacing | `[min, max, repeats]` where `repeats` is the number of times each value is repeated; number of unique points = `number_of_files / repeats` |
| `random_uniform` | Uniform random | `[min, max]` |
| `constant` | Fixed value | `value` |
| `custom` | Custom list, one value per file | `[v1, v2, v3, ...]`, of length `number_of_files` |
| `fix_ratio` | Ratio to another param | `[ref_param, multiplier]` |
| `staged` | Stage-varying values | `[v_stage0, v_stage1, ...]` or nested lists |

**Examples:**

```yaml
# Linear spacing: 10 unique values from 1 to 100, each used once
# (assumes number_of_files: 10, repeats=1 → 10/1 = 10 unique points)
species_A:
  - 'linspace'
  - [1, 100, 1]

# Linear spacing with repeats: 5 unique values, each repeated twice
# (assumes number_of_files: 10, repeats=2 → 10/2 = 5 unique points)
species_A:
  - 'linspace'
  - [1, 100, 2]

# Random uniform: values between 1e-6 and 1e-4
species_B:
  - 'random_uniform'
  - [1e-6, 1e-4]

# Constant: same value for all runs
temperature:
  - 'constant'
  - 25.0

# Custom: manually specified values
pH:
  - 'custom'
  - [6.0, 6.5, 7.0, 7.5, 8.0]

# Fix ratio: species_C = 0.1 * species_A
species_C:
  - 'fix_ratio'
  - [species_A, 0.1]
```

### Staged Restarts

Omphalos supports two-dimensional parameter variation through staged restarts:
- **Outer dimension (parallel)**: Independent runs with different initial conditions (e.g., `linspace`, `random_uniform`)
- **Inner dimension (sequential)**: Restart stages within each run where parameters can change at specific stages

This is useful for simulating scenarios where conditions change over time, such as shifts in boundary conditions or perturbation experiments.

> **Template requirements:** Your CrunchTope template must have a `spatial_profile` entry in the OUTPUT block (or its synonym `spatial_profile_at_time`, which CrunchTope and Omphalos both accept) — Omphalos uses this to offset output times across stages. Do not include `save_restart` or `restart` directives in the template; Omphalos sets these automatically.

> **Run chains with `rhea`, not `omphalos`.** Staged restarts are executed by the parallel runner; the sequential `omphalos` entry point does not run them, even with one file. `rhea config.yaml local` is the right command for a single-run chain.

#### Configuration

To enable staged restarts, add a `restart_chain` section to your config file:

```yaml
# Frontmatter (as usual)
template: 'input_file.in'
database: 'database.dbs'
number_of_files: 10    # Parallel runs (outer dimension)
nodes: 4

# Staged restart configuration
restart_chain:
    stages: 3          # Sequential stages (inner dimension)
    # Optional: specify spatial_profile times for each stage
    spatial_profile:
        - [0.5, 1.0, 1.5, 2.0]    # Stage 0 output times
        - [0.5, 1.0, 1.5, 2.0]    # Stage 1 times (auto-offset by 2.0)
        - [0.5, 1.0]              # Stage 2 times (auto-offset by 4.0)

# Parameter specification
concentrations:
    seawater:
        SO4--:
            - 'linspace'       # Varies across parallel runs
            - [1, 30]
        Ca++:
            - 'staged'         # Varies across sequential stages
            - [10.0, 15.0, 20.0]   # One value per stage
```

#### How it works

When `restart_chain` is specified:

1. For each parallel run, Omphalos generates one input file per stage (e.g., `input_stage0.in`, `input_stage1.in`, `input_stage2.in`)
2. Each stage's input file has:
   - `save_restart` directive (except the final stage) to save state for the next stage
   - `restart ... append` directive (except the first stage) to load state from the previous stage and append output to existing files
3. `spatial_profile` times are adjusted per stage so that output times are continuous across the full run:
   - **If `spatial_profile` is specified in `restart_chain`**: each stage uses the times you provide, offset by the cumulative duration of all previous stages (sum of the last time value from each preceding stage's list)
   - **If `spatial_profile` is omitted from `restart_chain`**: Omphalos reads the `spatial_profile` from your template's OUTPUT block and offsets it automatically by `stage_num × stage_duration`, where `stage_duration` is the last time in the template's list — so all stages have equal duration
4. Stages execute sequentially within each parallel run
5. Output files are numbered continuously across stages (e.g., pH1.tec through pH9.tec for 5+4 spatial profile times)

#### Execution flow

```
rhea config.yaml local
      |
      v
[Parallel across runs]
  run0 --> stage0 -> stage1 -> stage2 --> results
  run1 --> stage0 -> stage1 -> stage2 --> results
  run2 --> stage0 -> stage1 -> stage2 --> results
      |
      v
compile_results() --> results.nc
```

#### Changing grid resolution between stages

Stages may use different grids. The point is to run coarse to steady state, which is cheap, and then refine —
seeding the fine grid from the coarse solution for *every* species, which a zoned `INITIAL_CONDITIONS` cannot do.
Add a `grid` entry to `restart_chain`:

```yaml
restart_chain:
    stages: 2
    spatial_profile:
        - [4500]
        - [500]
    grid:
        - xzones: [100, 1.0]              # stage 0: 100 cells of 1 m
        - xzones: [80, 0.25, 20, 4.0]     # stage 1: 80 of 0.25 m, then 20 of 4 m
          porosity_file: fine_porosity.dat
```

`xzones` takes (cell count, cell width) pairs, so **graded grids work**: the stage above refines the first 20 m of
the column and coarsens the rest. Resampling maps by physical position, not by cell index, so the grading is
honoured. A regrid happens only when two stages declare different zones — including the case where the cell count
is unchanged and the cells are merely redistributed.

`refine: N` is shorthand for splitting every cell of the previous stage's grid into N:

```yaml
    grid:
        refine: 4        # stage 0 keeps the template's grid; each stage after it refines 4x
```

It also regenerates every spatial input file the deck reads — porosity, temperature, tortuosity, permeability —
at the new resolution. Without that a refined stage stops with `Fortran runtime error: End of file`, because
CrunchTope reads exactly `nx` rows from those files. A deck that reads no such files needs nothing extra.

##### How refined files are resampled

By default each fine cell takes the value of the coarse cell containing it. Choose otherwise by giving `refine`
as a mapping:

```yaml
    grid:
        refine:
            factor: 10
            method: linear       # step (default) | linear | smoothstep
```

| method | what it does |
|---|---|
| `step` | Replicates each value `factor` times. Cannot produce a value that was not already in the file. |
| `linear` | Interpolates between coarse **cell centres**, so a change between two coarse cells is spread over the `factor` fine cells spanning them. |
| `smoothstep` | The same ramp width, but weighted by the cubic `3t² − 2t³`, so there is no slope discontinuity at either end of it. |

**Which one is right depends on your field, not on the code.** `step` is the default because it cannot invent
structure, and it is the right choice where the steps are real — a lithological contact, say. It is the wrong
choice where the steps are an artefact of how the field was binned, and a layered `read_PorosityFile` usually
is: porosity enters transport as `phi**cementation_exponent`, so a step the coarse grid was too blunt to
resolve becomes a discontinuity in the diffusion coefficient that the fine grid then resolves faithfully — as a
staircase in your results. Refining a diffusion-dominated column tenfold with a large `cementation_exponent`,
`step` left about an order of magnitude more cell-to-cell variation in porosity than either ramp, and more again
in the `phi**cementation_exponent` transport sees; peak rates and depths were unaffected. Your field may be the
other way round.

Three details of the interpolating methods:

- They interpolate by **position**, not by cell index, so a graded grid is honoured. Because `refine` splits
  every coarse cell into equal parts, each coarse centre is recovered exactly as the mean of its fine centres.
- Neither overshoots the source range, and fine cells outside the first and last coarse centres clamp rather
  than extrapolate — so the boundary values are preserved.
- Only an **odd** factor puts a fine cell exactly on a coarse centre; with an even factor the centre falls
  between two fine cells, so no fine cell carries the original value unchanged.

The method applies to every file a stage regenerates. If one field wants step replication and another wants
smoothing, supply that file per stage by hand instead.

Handled for you, because a restart file overrides the deck and because CrunchTope validates the deck against the
new grid:

- `INITIAL_CONDITIONS` regions are rescaled to the new cell count, without which the stage aborts with
  `You have specified a corner at JX > NX`
- a per-stage `porosity_file` is injected into the restart file as well as written into the deck, because
  `CALL restart` runs after `CALL StartTope` and would otherwise supersede it
- `fix_porosity` is dropped from a stage that names a porosity file, since CrunchTope reads it first and skips
  the file read if it is set
- `pump` coordinates in a `FLOW` block are **not** rescaled — they name fixed cells, so a grid change warns about
  them and leaves them alone

In the results, each stage is placed on the grid of the stage with the most cells, and the cells a stage did not
cover are left NaN. Nothing is interpolated: every stored value is one the model produced. Where two grids do not
nest — so that two cells of one would collide on one cell of the other — the union of all stage positions is kept
instead, and that is reported.

##### The resampled restart is named for the grid it holds

A stage that changes grid reads a resampled copy of the previous stage's restart, not the file itself, so the
two-stage `refine: 4` chain above leaves both in `run0/`:

```
restart_0_stage0.rst         # 100 cells, as stage 0 wrote it
restart_0_stage0_nx400.rst   # the resampled copy stage 1 read
```

The suffix matters because a `.rst` carries no grid metadata and a Fortran unformatted read fills a short array
from a long record without error. Writing the resampled file back over its source would leave
`restart_0_stage0.rst` holding the *next* stage's resolution, so any later use of that name at face value — a
`restart_file` for another chain, an `inspect --nx 100` — would get a wrong initial state rather than a failure.

Stages sharing a grid are unaffected. A deck naming the same file for both directives keeps the old
replace-in-place behaviour.

See [`omphalos/examples/grid_refinement_chain`](omphalos/examples/grid_refinement_chain/) for a worked example,
including where a chain's answer legitimately departs from a cold start.

#### Starting from a spinup restart file

If you have a pre-run spinup model whose restart file you want all parallel runs to start from, use the `restart_file` frontmatter key alongside `restart_chain`. Omphalos will copy the specified `.rst` file into each run directory and use it as the starting state for stage 0:

```yaml
template: 'input_file.in'
database: 'database.dbs'
restart_file: 'spinup.rst'   # Copied to all run directories
number_of_files: 10

restart_chain:
    stages: 2

concentrations:
    seawater:
        SO4--:
            - 'linspace'
            - [1, 30]
```

Two things follow from the restart carrying its own clock and output counter, both handled for you:

- **Stage times stay durations.** A spinup stored at t = 2000 yr with `spatial_profile: [[500], [500]]`
  gives outputs at 2500 and 3000 yr — the stored clock is added to every stage. CrunchTope stops with
  `You have specified an output time < the restart time` if a stage asks for an output before the point
  it restarts from, so writing the first stage's times as absolute and the rest as durations would be
  the alternative.
- **Output file numbering continues from the restart.** `restart.F90` restores `nint`, which CrunchTope
  uses both to index the output times and to number the tecplot files, so a chain started from a spinup
  written after five outputs begins at `*6.tec`. Results parsing is offset to match; a run whose numbering
  looked like it began at 1 would find nothing to read.

If the file named by `restart_file` cannot be found or read when the input files are generated, the times
are set as though the chain starts from zero and a warning says so.

A spinup is used exactly as supplied: unlike a regridded file it gets no start-condition pass, so its stored
previous-step arrays stay as CrunchTope wrote them. That is deliberate — applying the pass to a spinup that
failed both start conditions gave bit-identical results. In `timestep.F90` the stored history reaches the step
only through `SQRT(|rnum/rden|)`, which is discarded unless it falls below the `MIN(2*delt, dtmax, tstep)` cap,
and on a near-steady spinup it does not. To apply it anyway, do it by hand and point `restart_file` at the
output:

```bash
python -m omphalos.restart_file regrid spinup.rst --nx-in 350 --nx-out 350 -o clean.rst --input model.in
```

##### Sharing one spinup across a sweep

Modifications reach every stage, so `number_of_files: N` computes stage 0 N times — concurrently, each with that
run's swept values. Where the sweep does not act on the coarse solution, or where a common initial state is what
you want, compute it once: run the coarse model alone (`number_of_files: 1`, no `grid`), then point every run's
`restart_file` at the restart it leaves behind.

That is a change of model rather than an optimisation. The N coarse solutions differ whenever a swept parameter
enters the spinup, and collapsing them to one discards that difference, so it is not done for you.

##### Timestep control in a restarted stage

`timestep_max` is honoured — the restart file does not carry it. `timestep_init` is the one to watch: `delt` *is*
discarded, so a restarted stage climbs from `timestep_init` by doubling. Raising it for the later stages of a
chain cut one stage's cost by a third here. Both take per-stage values via the `staged` method under `runtime:`.

#### Single sequential chain (no parallelism)

For a simple linear restart chain with no parallel variation, set `number_of_files: 1`:

```yaml
template: 'input_file.in'
database: 'database.dbs'
number_of_files: 1
nodes: 1

restart_chain:
    stages: 3
```

#### Combining with other parameter methods

The `staged` method can be combined with other parameter methods. Parameters using `linspace`, `random_uniform`, etc. will vary across parallel runs but remain constant across stages within each run. Parameters using `staged` will vary across stages but have the same stage-values across all parallel runs.

```yaml
restart_chain:
    stages: 2

concentrations:
    condition_a:
        SO4--:
            - 'linspace'      # Different value in each parallel run
            - [1, 30]
        Ca++:
            - 'staged'        # Same across runs, different per stage
            - [0.5, 2.0]
    condition_b:
        Acetate:
            - 'staged'        # Multiple conditions can use staged
            - [0.1, 5.0]
```

#### Per-run values within stages (nested lists)

By default, `staged` applies the same value to all parallel runs at each stage. To specify different values for each run within a stage, use a nested list:

```yaml
restart_chain:
    stages: 2

number_of_files: 3  # 3 parallel runs

concentrations:
    condition_a:
        Ca++:
            - 'staged'
            - [0.5, [1.0, 2.0, 3.0]]  # Stage 0: all runs = 0.5
                                       # Stage 1: run0 = 1.0, run1 = 2.0, run2 = 3.0
```

This allows full control over parameter values in both dimensions:
- Scalar value: same for all runs at that stage
- List value: different value per run at that stage (length must equal `number_of_files`)

---

## Project Structure

```
omphalos/
├── core/                    # Shared core modules
│   ├── parameter_methods.py # Parameter generation functions
│   ├── keyword_block.py     # Block object classes
│   ├── file_methods.py      # File I/O utilities
│   ├── attributes.py        # DataFrame extraction
│   └── spatial_constructor.py
├── omphalos/                # CrunchTope-specific code
│   ├── main.py              # Sequential entry point
│   ├── template.py          # Template parsing
│   ├── input_file.py        # InputFile class
│   ├── generate_inputs.py   # File generation
│   ├── run.py               # Simulation execution
│   ├── restart_file.py      # Read/regrid CrunchTope .rst restart files (also a CLI)
│   ├── example.yaml         # Annotated reference config
│   └── examples/            # Worked examples (quartz_flow_sweep, grid_refinement_chain,
│                            #   cesium_exchange, quartz_pressure_series,
│                            #   isotope_pressure_series)
├── pflotran/                # PFLOTRAN-specific code
│   └── ...
├── min3p/                   # MIN3P-specific code
│   ├── main.py              # Sequential entry point
│   ├── schema.py            # Per-block sub-keyword vocabulary
│   ├── keyword_block.py     # Line-preserving block data model
│   ├── template.py          # .dat template parsing
│   ├── input_file.py        # InputFile: print() + get_results()
│   ├── file_methods.py      # TecPlot output parsing (spatial/breakthrough/batch)
│   ├── generate_inputs.py   # MIN3P_IDs + configure_input_files() + restart chains
│   ├── run.py               # Simulation execution
│   ├── example_min3p*.yaml  # Annotated reference configs (plain, transport, restart chain)
│   └── examples/            # Worked examples (e.g. dissol_sweep: config + notebook)
├── rhea/                    # Parallel execution
│   ├── main.py              # Parallel entry point
│   ├── slurm_interface.py   # SLURM utilities
│   └── slurm_exec.py        # Worker script
├── coeus/                   # Analysis & visualization
│   ├── helper.py            # Data loading and error filtering
│   ├── plots.py             # Plotting utilities
│   ├── pflotran.py          # PFLOTRAN HDF5 utilities
│   ├── collate_pf.py        # Collate PFLOTRAN results from run directories
│   ├── compile_inputs.py    # Compile varied input conditions into conditions.nc
│   ├── context.py           # sys.path setup for sibling package imports
│   ├── retrieval_run.py     # Recover results from failed rhea runs
│   ├── analysis.ipynb       # Interactive analysis notebook
│   └── ExamplePlotting.ipynb  # Example plots for results.nc output
└── tests/                   # Test suite
    ├── unit/                # Unit tests
    └── integration/         # Integration tests
```

---

## Testing

The project includes a comprehensive test suite with **1079 tests**:

```bash
# Run all tests
pytest tests/ -v

# Run with coverage report
pytest tests/ --cov=core --cov=omphalos --cov-report=html

# Run specific test module
pytest tests/unit/test_parameter_methods.py -v

# Run specific test class
pytest tests/unit/test_keyword_block.py::TestConditionBlock -v
```

### Test Categories

Per-module counts are deliberately left out — they go stale as soon as anyone adds a test. Run
`pytest --collect-only -q -o addopts=''` for the current breakdown.

`tests/unit` mocks the solver and needs nothing installed. The smoke tests run one: `test_smoke.py` puts
CrunchTope to the shipped deck and to databases Omphalos has edited, augmented and added an isotope to;
`test_smoke_min3p.py` puts MIN3P to the `appelo` and `dissol` benchmarks, a deck generated from a sweep,
and a restart chain. Both check that what Omphalos writes is a file the solver reads and that a swept
value reaches it. Skipped without a binary, and marked `smoke`, so `pytest -m 'not smoke'` leaves them out.

| Module | Covers |
|--------|--------|
| `tests/unit/test_parameter_methods.py` | `core/parameter_methods.py` — the parameter generation methods (`linspace`, `random_uniform`, `constant`, `custom`, `fix_ratio`, `staged`) |
| `tests/unit/test_keyword_block.py` | `core/keyword_block.py` — the `KeywordBlock` and `ConditionBlock` objects |
| `tests/unit/test_file_methods.py` | `core/file_methods.py` — input file line searching, TecPlot output parsing, pickling, netCDF writing |
| `tests/unit/test_template.py` | `omphalos/template.py` — template parsing: keyword and condition blocks, comments, blank lines, FLOW zone entries |
| `tests/unit/test_generate_inputs.py` | `omphalos/generate_inputs.py` — config evaluation and input file generation |
| `tests/unit/test_spatial_constructor.py` | `core/spatial_constructor.py` — the spatial initial-condition array and its column ordering |
| `tests/unit/test_attributes.py` | `core/attributes.py` — attribute tables and their file_num labelling |
| `tests/unit/test_compile_inputs.py` | `coeus/compile_inputs.py` — the record of what a sweep actually ran |
| `tests/unit/test_run.py` | `omphalos/run.py` — CrunchTope invocation and the stdout error patterns |
| `tests/unit/test_restart_file.py` | `omphalos/restart_file.py` — reading, regridding and verifying CrunchTope `.rst` restart files, against a real 10-cell fixture |
| `tests/unit/test_database.py` | `omphalos/database.py` — parsing, round-trip fidelity and surgical editing of a `.dbs` |
| `tests/unit/test_database_sweep.py` | `database_parameters` end to end: per-run databases, staged chains, config errors |
| `tests/unit/test_logk.py` | `omphalos/logk.py` — pyGCC log K recomputation, stoichiometry reconciliation, regridding |
| `tests/unit/test_isotopes.py` | `omphalos/isotopes.py` — isotope insertion, checked by rebuilding the hand-built systems |
| `tests/unit/test_crunch_keywords.py` | `omphalos/crunch_keywords.py` — which auxiliary-database keywords a build reads |
| `tests/unit/test_namelist.py` | `omphalos/namelist.py` — Fortran namelist (aqueous database, catabolic pathways) editing |
| `tests/unit/test_min3p.py` | `min3p/` — the MIN3P backend: schema, template parsing, output parsing, restart chains |
| `tests/unit/test_slurm_interface.py` | `rhea/slurm_interface.py` — result compilation, failed-run accounting, run-directory clearing |
| `tests/unit/test_slurm_exec.py` | `rhea/slurm_exec.py` — that each run, and each stage, reads and writes its own auxiliary files |
| `tests/unit/test_coeus_helper.py` | `coeus/helper.py` — result loading and error filtering |
| `tests/integration/test_omphalos_workflow.py` | End-to-end workflows across the modules above |
| `tests/integration/test_smoke.py` | CrunchTope run against the decks and databases Omphalos writes |
| `tests/integration/test_smoke_min3p.py` | MIN3P run against the decks Omphalos writes, including a restart chain |

---

## Analysis with Coeus

The `coeus` module provides tools for loading, filtering, and visualising Omphalos results after a run completes.

### Loading and Filtering Results

Use `filter_errors` to separate successful runs from those that failed or timed out, and to print a summary of the failure rate:

```python
from coeus.helper import filter_errors
from omphalos.file_methods import unpickle

raw = unpickle('inputs.pkl')
dataset, errors = filter_errors(raw)
# Returned 98 files without errors out of a total possible 100.
# 2 files had errors.
# File failure rate: 2.0 %.
```

Both returned dictionaries are new and keyed by run number, and `raw` is left untouched, so the successes and
failures can be compared afterwards and either can be joined against `results.nc` on `file_num`.

Or use `quick_import` as a one-liner that loads and filters in a single call:

```python
from coeus.helper import quick_import

dataset = quick_import('inputs.pkl')
```

`filter_errors` accepts a `verbose=True` argument to list the runs that failed and the error code each
carried.

### Attribute Tables

`core/attributes.py` turns the input side of a sweep into tables suitable for regression or ML features. Each is
keyed by run number — `file_num` — so it joins onto `results.nc` and `conditions.nc` without relying on position,
which matters as soon as a run fails and drops out:

```python
from core import attributes as attr
from coeus.helper import quick_import

dataset = quick_import('inputs.pkl')

concs = attr.get_condition(dataset, 'seawater', species_concs=True)   # DataFrame, indexed by file_num
inflow = attr.boundary_condition(dataset, boundary='x_begin')          # DataFrame, indexed by file_num
rates = attr.mineral_rates(dataset)                                   # DataFrame, indexed by file_num
spatial = attr.initial_conditions(dataset, concentrations=True)        # Dataset, file_num coordinate
```

`initial_conditions` builds the spatial initial state cell by cell from the `INITIAL_CONDITIONS` regions, taking
every condition block into account. Its variables are ordered by `core.spatial_constructor.condition_variables`,
which is also what orders the underlying array — use that function if you need the ordering yourself. Grid cells
that no condition region covers are left at zero and reported.

pH is not a primary species concentration in a CrunchTope condition block but a parameter alongside `temperature`,
so it never appears among the concentrations and has to be asked for by name:

```python
spatial = attr.initial_conditions(dataset, concentrations=True, ph=True)   # adds a 'pH' variable
```

The value is reported as pH, not converted to `[H+]`: CrunchTope's pH is −log₁₀ of the H⁺ *activity*, and
recovering a concentration needs the activity coefficients that only the speciation solve produces. The `pH`
column comes last, so switching it on leaves the species columns where they were. A condition that constrains H⁺
directly, or by charge balance (`pH charge`), reads `nan` rather than borrowing a neighbouring condition's value.

### Recovering Failed Runs

If a rhea run fails partway through, `retrieval_run.py` attempts to read whatever output was written to each `run*/` directory and compile it into a `results.nc` file:

```bash
# Recover all run directories for a given template and run count
python coeus/retrieval_run.py path/to/template.in <num_files>

# Recover output from a single CrunchTope run directory
python coeus/retrieval_run.py path/to/template.in 1 --single
```

This is useful when simulations were interrupted before `compile_results` could run.

### Collating PFLOTRAN Results

For PFLOTRAN runs, `collate_pf.py` walks all `run*/` directories in the current working directory, reads each `.h5` output file, and writes a combined `collated_runs_<timestamp>.nc` file:

```bash
cd /path/to/your/results
python /path/to/omphalos/coeus/collate_pf.py
```

This is an alternative to the standard `compile_results` path when working with PFLOTRAN output directly.

### Compiling Input Conditions

`compile_inputs` reads the completed `input_fileN_complete.pkl` files from each `run*/` directory and writes the
varied input parameters to a `conditions.nc` file, using the YAML config to determine which parameters to extract.

The simplest way to get it is to ask for it when starting the run, with `-c`:

```bash
rhea config.yaml local --compile-inputs
```

The record is written straight after the results, into the same working directory and named to match: alongside
`results.nc` it is `conditions.nc`, alongside `results1.nc` it is `conditions1.nc`. The flag applies to local
CrunchTope and MIN3P runs: a cluster submission returns before its array has finished, and PFLOTRAN has no reader
here, so in those cases it says so and skips rather than writing something misleading. If compiling the record
fails, the run still reports its results — the failure is a warning, not an error.

Run by hand, the script writes `conditions.nc` unless told otherwise, since it has no way of knowing which sweep
you mean. Where several `results*.nc` exist it says so and shows the pairing, so pass `-o` to match the one you
want:

```bash
python /path/to/omphalos/coeus/compile_inputs.py config.yaml -o conditions1.nc   # pairs with results1.nc
```

It can equally be run after the fact, from the directory holding the run directories:

```bash
cd /path/to/your/results
python /path/to/omphalos/coeus/compile_inputs.py config.yaml
```

An alternative output filename can be specified with `-o`:

```bash
python /path/to/omphalos/coeus/compile_inputs.py config.yaml -o my_conditions.nc
```

Or call it directly, which is what the flag does:

```python
from coeus.compile_inputs import compile_inputs

summary = compile_inputs(config, output='conditions.nc', directory='.')
# {'output': PosixPath('conditions.nc'), 'groups': 3, 'runs': [0, 1, 2], 'missing': []}
```

The output is a netCDF file with groups mirroring the YAML config structure:

- `concentrations/<condition>`, `parameters/<condition>`, `mineral_volumes/<condition>` — geochemical condition entries, each a variable with a `file_num` dimension
- `flow`, `runtime`, `mineral_rates`, etc. — keyword block entries
- `namelists/<type>/<reaction>` — namelist parameters

This is particularly useful for runs using `random_uniform` parameter sampling, where the actual values used cannot be recovered from the YAML alone.

For staged runs (configs with a `restart_chain` block), the script detects staging automatically and re-derives `staged` parameter values from the YAML for each stage. All output variables in a staged run include a `stage_num` dimension alongside `file_num`. Parameters that do not use the `staged` method are read from the pickles as normal and tiled across stages.

A MIN3P sweep names positional coordinates under `modifications:` rather than keyword blocks, so its record is a
single `modifications` group with a variable per entry. Pass `-m` to read a run that way, as you would to `rhea`:

```bash
python /path/to/omphalos/coeus/compile_inputs.py config.yaml -m
```

An enumerated value (`'geometric'`) is recorded as text, not a column of NaNs. A MIN3P chain varies only its stage
final times, so its values are tiled across `stage_num` rather than re-derived.

The conditions can then be loaded alongside results for combined analysis:

```python
import xarray as xr

results = xr.open_dataset('results.nc', group='totcon')
conditions = xr.open_dataset('conditions.nc', group='parameters/initial')
```

### Plotting Utilities

`coeus/plots.py` provides helper functions for working with xarray datasets:

- **`prod_vars(file, category, vars, name)`** — creates a new variable in the dataset that is the element-wise product of a list of existing variables
- **`format_axis(axis, font_props, category, plot_var, column)`** — applies consistent axis formatting for CrunchTope depth-profile plots, including category-appropriate axis labels and symlog scaling for `rate` and `saturation` output

### Example Notebooks

Two notebooks are provided in `coeus/`:

- **`ExamplePlotting.ipynb`** — demonstrates loading `results.nc` groups with xarray, selecting slices by coordinate, plotting depth profiles and heatmaps, and animating output across `file_num` and `time` dimensions
- **`analysis.ipynb`** — interactive analysis notebook for exploring results using the coeus helper functions

### Worked Examples

Each worked example is a self-contained directory holding a template, a sweep config, a notebook that takes the
sweep from config to figure, and a README:

- [`omphalos/examples/quartz_flow_sweep`](omphalos/examples/quartz_flow_sweep/) — **CrunchTope + rhea**: ten runs
  sweeping the Darcy flux through a kinetically dissolving quartz column, recovering the linear scaling of
  equilibration length with flow rate. Start here for the end-to-end workflow: config → `rhea` → `results.nc` +
  `conditions.nc` → analysis.
- [`omphalos/examples/grid_refinement_chain`](omphalos/examples/grid_refinement_chain/) — **CrunchTope + rhea**:
  a staged restart chain that changes grid resolution between stages, reaching a 400-cell answer for a third of
  the cold-start cost. Also shows where a chain's answer legitimately departs from a cold start, and why.
- [`omphalos/examples/cesium_exchange`](omphalos/examples/cesium_exchange/) — **CrunchTope + rhea**: an
  ion-exchange selectivity coefficient swept in the *thermodynamic database*, where no keyword block can reach
  it. Each run's `.dbs` differs from the template on at most one line — the middle run is the fitted
  value the sweep brackets, so its database is byte-identical.
- [`omphalos/examples/quartz_pressure_series`](omphalos/examples/quartz_pressure_series/) — **CrunchTope +
  rhea**: a database whose log K columns are recomputed with pyGCC at a different pressure for each run, taking
  a quartz column from 1 km to 4 km depth. Shows how to record a parameter the database itself cannot carry.
- [`omphalos/examples/isotope_pressure_series`](omphalos/examples/isotope_pressure_series/) —
  **CrunchTope + rhea**: `database_isotopes` and `database_logk` together, the one combination that
  needs care. pyGCC cannot recompute an isotopologue, so a recomputation would separate it from its
  parent and invent a fractionation; this shows the pair held together across a pressure series, and
  how large the invented fractionation would have been.
- [`min3p/examples/dissol_sweep`](min3p/examples/dissol_sweep/) — **MIN3P**: a calcite dissolution front driven by
  varying inflow acidity.
- [`min3p/examples/velocity_sweep`](min3p/examples/velocity_sweep/) — **MIN3P**: an advective pH front and Darcy's
  law, driven by varying the flow gradient.

---

## Advanced Topics

### Non-Unique Entries

For minerals with parallel reaction mechanisms, use the `{mineral}&{label}` format:

```yaml
mineral_rates:
  # Default mechanism
  Calcite&default:
    - 'random_uniform'
    - [1e-12, 1e-10]

  # Acid mechanism
  Calcite&h+:
    - 'random_uniform'
    - [1e-11, 1e-9]
```

> **Important:** Do not use ampersands (`&`) in mineral names in your input files.

The same `&` convention covers the keywords CrunchTope allows to repeat within a block. Entries are
keyed on the leftmost word, so these would otherwise overwrite each other; the token after the keyword
makes the key unique:

| Block | Keyword | Key format | Repeats because |
|-------|---------|------------|-----------------|
| `OUTPUT` | `time_series` | `time_series&<filename>` | one per output location |
| `ION_EXCHANGE` | `exchange` | `exchange&<exchanger>` | one per exchanger |
| `TRANSPORT` | `D_25` | `D_25&<species>` | one per species |

```yaml
transport:
  # Vary the diffusion coefficient of one species only
  D_25&Ca++:
    - 'linspace'
    - [0.5e-9, 1.0e-9, 1]
```

Naming the bare keyword (`D_25`) works while the template has only one such line; if there are
several, Omphalos reports the candidates rather than picking one.

The `FLOW` block repeats `permeability_x`, `permeability_y`, `permeability_z` and `pressure` to cover
non-contiguous regions, so those are keyed by their coordinate set instead — `<keyword> i-i j-j k-k`,
in the order the line writes them. A `default` entry, having no zone, keeps the bare keyword. Quote the
key, since it contains spaces:

```yaml
flow:
  # Vary the permeability of one zone, leaving the other entries alone
  'permeability_X 22-33 1-42 1-1':
    - 'custom'
    - [1.024e-12, 1.024e-13, 1.024e-14, 1.024e-15]
```

Case follows the template: the key repeats the keyword as the deck spells it, which CrunchTope reads
case insensitively either way. `pump` is keyed on its coordinates too, as `pump&i&j&k`.

### Line Continuation

Long entries may be continued across lines with a trailing ampersand, as the manual documents for
`spatial_profile`, `time_series_print` and `MakeMovie`:

```
spatial_profile 100.0 200.0 &
                300.0 400.0
```

Omphalos joins these into a single entry when reading, so `spatial_profile` above is four output times
rather than two plus a stray `&`. On writing, an entry that would exceed CrunchTope's 132 character
line limit is wrapped back across lines the same way — previously an over-long `spatial_profile` was a
hard error telling you to use more stages.

### Pump Keyword in FLOW Block

The `pump` keyword in CrunchTope specifies a pumping rate at a specific grid cell location. In the input file, it appears as:

```
pump <rate> <condition_name> <x> <y> <z>
```

When modifying pump rates in Omphalos, the keyword includes the cell location as part of the key using the format `pump&<x>&<y>&<z>`:

```yaml
flow:
  # Modify pump rate at cell (20, 1, 1)
  pump&20&1&1:
    - 'linspace'
    - [1e-8, 5e-8, 1]
```

This can also be combined with staged restarts to change pump rates between stages:

```yaml
restart_chain:
    stages: 2

flow:
  pump&20&1&1:
    - 'staged'
    - [1.1574e-8, 5.0e-8]  # Stage 0: low rate, Stage 1: high rate
```

> **Note:** The cell indices in the key must match the location specified in your template input file.

### Choosing a Parallelization Backend

Local runs distribute simulations across cores with `xargs` by default, which needs nothing beyond a POSIX shell.
GNU Parallel is available as an alternative and offers more sophisticated load balancing and progress reporting:

```bash
python -m rhea.main config.yaml local -b parallel
```

On some systems GNU Parallel computes a negative limit for its command line and refuses to run anything at all:

```
parallel: Error: Command line too long (20 >= -5564) at input 0: 0
```

This is a quirk of Parallel's own limit calculation on that platform, not of the command Omphalos builds — it
happens for a bare `parallel echo hello ::: 1` too. There is no workaround from this side, so stay on `xargs`
where you see it. `xargs` is simpler but equally effective for most workloads.

### Cluster Runs

`rhea <config> cluster` submits `rhea/prep_directories.sh` as a job array, waits for it, then submits
`rhea/run_input_file.sbatch` as a second array. Site-specific settings come from the environment rather than being
edited into the batch scripts:

| Variable | Meaning |
|----------|---------|
| `OMPHALOS_DIR` | Path to the checkout. Exported automatically by `rhea/main.py`; falls back to `SLURM_SUBMIT_DIR` |
| `OMPHALOS_MODULES` | Modules to load, space separated, e.g. `"Python/3.10.8-GCCcore-12.2.0 OpenMPI/4.1.5-GCC-12.2.0"` |
| `OMPHALOS_PYTHON` | Python to run the workers with (default: `python`) |
| `OMPHALOS_PROFILE` | Shell profile to source first, e.g. `"$HOME/.bashrc"` (used by `parallel.sbatch`) |
| `OMPHALOS_ENV` | Conda environment to activate (default: `omphalos`, used by `parallel.sbatch`) |

Set them in your shell before submitting:

```bash
export OMPHALOS_MODULES="Python/3.10.8-GCCcore-12.2.0 OpenMPI/4.1.5-GCC-12.2.0"
rhea config.yaml cluster
```

Resource directives (`--mem-per-cpu`, `--time`, mail options) are the two `.sbatch` files' own business — edit
them for your site, or pass overrides on the `sbatch` command line.

> **Status:** the cluster path has not been exercised since the batch scripts were generalised; it is the least
> tested part of the project. Check the first submission by hand.

### Inspecting a Restart File

`omphalos/restart_file.py` doubles as a command-line tool for looking inside a CrunchTope `.rst`,
which is otherwise an opaque Fortran dump. It is the thing to reach for when a chain fails.

```bash
# What is in the file, and how each record decomposes onto the grid
python -m omphalos.restart_file inspect run.rst --nx 350 --input model.in

# Is the layout understood? Round-trips byte-identically, matches the tecplot output,
# and reports the state invariants a restart depends on
python -m omphalos.restart_file verify run.rst --nx 350 --input model.in \
    --identity --reference . --file-num 12 --invariants

# Resample onto a different grid by hand
python -m omphalos.restart_file regrid run.rst --nx-in 350 --nx-out 3500 \
    -o fine.rst --input model.in --porosity-file porosity_fine.dat
```

Pass `--input` with the deck: it supplies the species counts that fix the leading array dimensions,
without which several records cannot be resolved. `--file-num` is the tecplot output the restart
corresponds to — a restart is written at the *end* of a run, so that is the last output, not the
first.

Two things `verify` reports separately, because they are not the same kind of statement.
`sp10 == exp(sp)` is a **true invariant** of any valid restart file and a failure means the file was
misread. `s == sn` and `spnO2 == spnnO2` are **start conditions** that regridding imposes so the
solver can begin from a tiny `timestep_init`; a CrunchTope-written file legitimately violates them,
because it holds two real time levels.

> **Source archaeology needs `grep -a`.** Most `.F90` files in the CrunchTope source are treated as
> binary by `grep`, because their copyright headers contain invalid UTF-8. A plain `grep` silently
> reports `Binary file matches` and nothing else, which is an easy way to conclude a subroutine is
> dead code when it is not.

### Keep the Working Directory Path Short

CrunchTope reads the input file path into a fixed-length buffer, so a deeply nested working directory gets
truncated and every run fails at startup with:

```
Error in file 0: "Cannot find input file".
```

`rhea` passes an absolute path to each run directory, so the limit applies to the whole path, not just the file
name. Run sweeps from a shorter path if you see this. Since CrunchTope waits on stdin after printing that message,
`'Cannot find input file'` is one of the `CT_ERROR_PATTERNS` in `omphalos/run.py` — otherwise each run would sit
until its `timeout` expired before being recorded as failed.

### Two-Dimensional Decks

Four things bite a 1-D deck that gains a second dimension. The first three are now `CT_ERROR_PATTERNS`.

- **`hindmarsh true` is 1-D only.** In 2-D CrunchTope prompts `Return to continue` and blocks on it. Set
  `hindmarsh false`.
- **`time_series` needs a Y node.** `time_series out.dat 251` is a 1-D form; in 2-D it stops with
  `Y location for timeseries must be specified`. Use `time_series_at_node out.dat 30 30`.
- **`pressure` zone entries need their K range.** `zone 43-43 1-42 fix` stops at startup with
  `No Z location for pressure`; it wants `zone 43-43 1-42 1-1 fix`. CrunchTope exits rather than hanging, so
  this was previously recorded as a successful run with no output.
- **`gimrt true` can transport nothing in 2-D, silently.** No message, so no pattern can catch it: the run
  completes, solves flow, writes output, and no solute moves. Prefer `gimrt false` (OS3D), and check a tracer
  actually moves.

Failed and timed-out runs now have their CrunchTope process force-closed, since several patterns are printed
by a process that then blocks.

### PFLOTRAN Support

Enable PFLOTRAN mode with the `-p` flag:

```bash
python -m rhea.main config.yaml local -p
```

> **Note:** Staged restarts (`restart_chain`) are not currently supported in PFLOTRAN mode.

### MIN3P Support

Run MIN3P either sequentially via its own entry point, or in parallel through `rhea` with the `--min3p` flag (short form `-m`). The examples use the long form to avoid visual clash with Python's own `-m` module flag:

```bash
# Sequential
python -m min3p.main config.yaml records.pkl

# Parallel (local)
python -m rhea.main config.yaml local --min3p

# ... and with a record of the parameter values each run used
python -m rhea.main config.yaml local --min3p --compile-inputs
```

MIN3P input files are positional (block-structured `.dat`, not key-value), so a
sweep is driven by an explicit `modifications` block naming each parameter's
coordinate (block / sub-keyword / line / token). See [`min3p/example_min3p.yaml`](min3p/example_min3p.yaml):

```yaml
template: appelo.dat
number_of_files: 3
timeout: 120
database_directory: /path/to/MIN3P/database/default   # repoints the template's DB path
modifications:
  calcite_volume:
    alias: calcite_volume        # or spell out block/keyword/line/token
    method: linspace
    params: [0.005, 0.02]
```

MIN3P reads its auxiliary inputs as `<run name>.<ext>` — `.hyc` for a hydraulic conductivity field,
`.ivs` for an initial condition, `.bcvs` for transient boundary conditions, and the porosity, CEC,
Skempton, specific-storage, energy-balance, mineral and unstructured-grid variants — so the deck
never names them. Omphalos copies every such file beside the template into each run directory,
along with `solver.cfg`; MIN3P's own output is excluded, carrying an index (`run_12.gsc`) that an
input never has. Withholding one is fatal, so anything unrecognised is copied rather than skipped.

Results are written to `results.nc` with one group per MIN3P output category,
concatenated over `file_num`. All field-output categories from the MIN3P User
Manual (Tables 2.3–2.6) are captured, in three families: spatial `gs*` + `vel`
(indexed by x,y,z), breakthrough `gb*` (time series at observation points), and
local/batch `lb*` (time series, or pH for pC-pH runs). Each family covers
concentrations, master variables (pH/alkalinity), gas pressures, mineral
volumes/saturation/rates, sorbed species, isotopes and activity coefficients.
Per-domain mass-balance and energy-balance *diagnostics* (`_o.*`, `.mac/.mae`,
`.cbt`, `.ebal*`, …) are not parsed into the dataset.

Worked end-to-end examples (sweep config + notebook + figure) live in
[`min3p/examples/`](min3p/examples/):
[`dissol_sweep`](min3p/examples/dissol_sweep/) — a calcite dissolution front
driven by varying inflow acidity; and
[`velocity_sweep`](min3p/examples/velocity_sweep/) — an advective pH front and
Darcy's law, driven by varying the flow gradient.

**Restart chains** continue a run across stages via MIN3P's `'restart'`
mechanism (each stage picks up from the previous stage's `restart.tmp` state).
Add a `restart_chain` block (see [`min3p/example_min3p_restart.yaml`](min3p/example_min3p_restart.yaml)):

```yaml
restart_chain:
  stages: 2
  final_times: [100.0, 200.0]   # final solution time per stage
  append: 'append results'      # how transient output resumes at the break point
```

Any `modifications` sweep is inherited by every stage. Each run's stages execute
sequentially in a per-run subdirectory so their restart state does not collide.

Only the final solution time is set per stage, so every stage still asks for the deck's `output
control` times. MIN3P refuses a run whose final time falls below one of them, so stages have to
extend past the deck's last output time rather than subdivide it.

> **Notes:** MIN3P mode currently supports `run_type local` only (cluster/sbatch
> is a TODO). See `min3p/examples/dissol_sweep/` for a runnable worked example.

---

## Citation

If you use Omphalos in published work, please cite:

> Fotherby, A; Bradbury, HJ; Druhan, JL; Turchyn, AV. (2023). **An emulation-based approach for interrogating reactive transport models.** *Geoscientific Model Development*, 16, 7059-7074. doi:[10.5194/gmd-16-7059-2023](https://doi.org/10.5194/gmd-16-7059-2023)

```bibtex
@article{fotherby2023emulation,
  title={An emulation-based approach for interrogating reactive transport models},
  author={Fotherby, Angus and Bradbury, Harold J and Druhan, Jennifer L and Turchyn, Alexandra V},
  journal={Geoscientific Model Development},
  volume={16},
  pages={7059--7074},
  year={2023},
  doi={10.5194/gmd-16-7059-2023}
}
```

---

## License

MIT License

Copyright © Angus Fotherby & Harold Bradbury (2019-2026)

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

