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
  <img src="https://img.shields.io/badge/tests-151%20passed-brightgreen" alt="Tests">
  <img src="https://img.shields.io/badge/python-3.8%2B-blue" alt="Python">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="License">
  <img src="https://img.shields.io/badge/CrunchTope-supported-orange" alt="CrunchTope">
  <img src="https://img.shields.io/badge/PFLOTRAN-supported-orange" alt="PFLOTRAN">
</p>

---

## Features

- **Simplify geochemical modelling** — Automate parameter sweeps and sensitivity analyses
- **Test thousands of combinations** — Generate and run hundreds to thousands of simulations effortlessly
- **Parallel execution** — Run simulations locally or on SLURM-managed clusters
- **Multiple simulators** — Support for both CrunchTope and PFLOTRAN
- **Unified results** — Collate all outputs into structured xarray/netCDF datasets
- **Flexible configuration** — YAML-based configuration for easy parameter specification

---

## Table of Contents

- [Installation](#installation)
  - [Linux/Mac](#linuxmac)
  - [Windows](#windows)
  - [Development Setup](#development-setup)
- [Quick Start](#quick-start)
- [Usage](#usage)
  - [Running Simulations](#running-simulations)
  - [Collecting Results](#collecting-results)
- [Configuration Guide](#configuration-guide)
  - [Frontmatter](#frontmatter)
  - [Parameter Modification](#parameter-modification)
  - [Modification Options](#modification-options)
- [Project Structure](#project-structure)
- [Testing](#testing)
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

---

## Quick Start

Omphalos requires two inputs:

1. **A working CrunchTope/PFLOTRAN model** — Your template input file
2. **A YAML configuration file** — Specifies how to vary model parameters

### Example Configuration

```yaml
# config.yaml
template: 'my_model.in'
database: 'thermodynamic.dbs'
timeout: 300
conditions: [seawater, sediment]
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
- `-d, --debug` — Generate files without running simulations
- `-b, --backend` — Parallelization backend: `parallel` (GNU Parallel, default) or `xargs`

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

---

## Configuration Guide

### Frontmatter

| Keyword | Description | Required | Example |
|---------|-------------|----------|---------|
| `template` | Path to template input file | Yes | `model.in` |
| `database` | Path to thermodynamic database | Yes | `database.dbs` |
| `aqueous_database` | Path to aqueous database | No | `aqueous.dbs` |
| `catabolic_pathways` | Path to catabolic pathways | No | `CatabolicPathways.in` |
| `restart_file` | Existing restart file to copy to all runs | No | `spinup.rst` |
| `timeout` | Max simulation time (seconds) | Yes | `300` |
| `conditions` | List of conditions to modify | Yes | `[boundary, initial]` |
| `number_of_files` | Number of simulations | Yes | `100` |
| `nodes` | Parallel workers/SLURM nodes | Yes | `4` |

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
| `EROSION/BURIAL` | `erosion/burial` |

> **Note:** Block names in your CrunchTope input file must be written in CAPITALS (e.g., `RUNTIME`, `FLOW`, `MINERALS`).

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
| `parameters` | Temperature, pH, etc. |

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
```

#### Namelists

Modify auxiliary files (aqueous database, catabolic pathways):

```yaml
namelists:
  aqueous_kinetics:
    sulfate_reduction:
      rate:
        - 'random_uniform'
        - [1e-10, 1e-8]
```

### Modification Options

| Option | Description | Syntax |
|--------|-------------|--------|
| `linspace` | Linear spacing | `[min, max, repeats]` |
| `random_uniform` | Uniform random | `[min, max]` |
| `constant` | Fixed value | `value` |
| `custom` | Custom list | `[v1, v2, v3, ...]` |
| `fix_ratio` | Ratio to another param | `[ref_param, multiplier]` |
| `staged` | Stage-varying values | `[v_stage0, v_stage1, ...]` or nested lists |

**Examples:**

```yaml
# Linear spacing: 10 values from 1 to 100
species_A:
  - 'linspace'
  - [1, 100, 1]

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
   - `restart` directive (except the first stage) to load state from the previous stage
3. Stages execute sequentially within each parallel run
4. Results from all stages are concatenated along the time dimension

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
│   └── run.py               # Simulation execution
├── pflotran/                # PFLOTRAN-specific code
│   └── ...
├── rhea/                    # Parallel execution
│   ├── main.py              # Parallel entry point
│   ├── slurm_interface.py   # SLURM utilities
│   └── slurm_exec.py        # Worker script
├── coeus/                   # Analysis & visualization
│   ├── helper.py            # Data loading utilities
│   └── plots.py             # Plotting functions
└── tests/                   # Test suite
    ├── unit/                # Unit tests
    └── integration/         # Integration tests
```

---

## Testing

The project includes a comprehensive test suite with **151 tests**:

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

| Category | Tests | Description |
|----------|-------|-------------|
| `test_parameter_methods.py` | 45 | Parameter generation functions |
| `test_keyword_block.py` | 25 | Block object classes |
| `test_file_methods.py` | 23 | File I/O operations |
| `test_generate_inputs.py` | 21 | Input file generation |
| `test_template.py` | 27 | Template parsing |
| `test_omphalos_workflow.py` | 10 | Integration tests |

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

### PFLOTRAN Support

Enable PFLOTRAN mode with the `-p` flag:

```bash
python -m rhea.main config.yaml local -p
```

> **Note:** Staged restarts (`restart_chain`) are not currently supported in PFLOTRAN mode.

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

