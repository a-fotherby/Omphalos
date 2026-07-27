# CrunchTope + rhea worked example — flow-rate sweep on a quartz column

An end-to-end Omphalos experiment on the CrunchTope backend, run in parallel with `rhea`: one template, one
config, ten simulations, one figure. The MIN3P equivalents live in `../../../min3p/examples/`.

## Problem

A dilute water is injected into a 100 m column of quartz sand (`quartz_column.in`, adapted from the CrunchTope
short-course exercise `Exercises/Ex2Advection/ShortCourse2react.in`). Quartz dissolves kinetically towards
equilibrium as the water advects, so the Si the fluid picks up is set by how long it spends in the column. The
sweep varies the **Darcy flux** (`FLOW` / `constant_flow`) over three orders of magnitude,
`[0.1, 0.25, 0.5, 1, 2.5, 5, 10, 25, 50, 100]` m yr⁻¹.

The measured quantity is the *equilibration length* — the distance the fluid must travel to reach 95% of quartz
saturation. For a first-order approach to equilibrium it should be linear in the Darcy flux and pass through the
origin, with a slope fixed by the rate constant, the reactive surface area and the porosity.

## Contents

| File | What it is |
|------|-----------|
| `quartz_column.in` | CrunchTope template: 1-D advective column, kinetic quartz dissolution, Si isotopes |
| `datacom.dbs` | Thermodynamic database used by the template |
| `quartz_flow_sweep.yaml` | Sweep config: 10 runs varying `FLOW`/`constant_flow` |
| `quartz_flow_sweep.ipynb` | Reads `results.nc` + `conditions.nc`, checks for steady state and plots the outcome |
| `quartz_flow_sweep.png` | The figure produced by the notebook |
| `results.nc`, `conditions.nc` | Sweep output and the record of what was varied (git-ignored; regenerable) |
| `run0/ … run9/` | Per-run working directories written by `rhea` (git-ignored; regenerable) |

## Reproduce

The sweep is run offline, in the shell; the notebook then reads what it produced.

```bash
cd omphalos/examples/quartz_flow_sweep
conda activate omphalos

# 1. Generate the ten input files and run them in parallel (~5 s in total).
rhea quartz_flow_sweep.yaml local -b xargs

# 2. Record the parameter values that were actually used, alongside the results.
python ../../../coeus/compile_inputs.py quartz_flow_sweep.yaml

# 3. Regenerate the figure and notebook outputs (any env with xarray + matplotlib).
conda run -n JupyterEnv jupyter nbconvert --to notebook --execute --inplace quartz_flow_sweep.ipynb
```

Steps 1 and 2 need a working CrunchTope binary, configured in `omphalos/settings.py` by `install.sh`. Step 3
needs only `xarray` and `matplotlib`, so the analysis travels: copy the two netCDF files anywhere and open the
notebook there.

`rhea` is the alias `install.sh` adds for `python <repo>/rhea/main.py`; without it, call the script directly.
`-b xargs` avoids a GNU Parallel *"command line too long"* failure seen on some machines — see the
Troubleshooting section of the top-level README. Drop it if GNU Parallel behaves on yours.

## The result

- **Transport control.** The steady-state Si profile stretches out with flow rate: at 0.1 m yr⁻¹ the fluid is at
  quartz saturation within the first metre, while at 100 m yr⁻¹ it takes ~35 m. Every run still leaves the column
  saturated, so a whole-column measurement would see nothing — the sweep is what exposes the length scale.
- **Kinetic scaling.** Equilibration length is linear in the Darcy flux through the origin (R² ≈ 0.998), with a
  fitted slope of 0.354 m per m yr⁻¹ against 0.329 predicted from the rate constant (`-rate -9.5`), the surface
  area (`bulk_surface_area 100`) and the porosity alone — agreement to 8%, which also confirms that CrunchTope's
  `bulk_surface_area` is m² per m³ of bulk medium. The residual is what the affinity term in the rate law and the
  1 m grid would lead you to expect.
- **Fluid steady state ≠ mineral steady state.** The fluid profile stops changing after ~100 yr, but quartz keeps
  dissolving: by 5 kyr the fastest runs have stripped 16% of the quartz near the inlet. The notebook checks both
  before trusting the 1000 yr slice.

## Writing a template Omphalos can read

Three things that used to bite here, and no longer do:

- `!` comments and blank lines are fine anywhere, inside keyword blocks included. They are stripped when the
  template is read, so they do not survive into the generated `run*/` input files.
- This template has no gas chemistry and so declares no `GASES` block. Any block the input file does not declare
  simply contributes no names when condition entries are sorted.
- Condition blocks may be written `CONDITION`, `Condition` or `condition`, as CrunchTope itself allows. Only the
  `CONDITION` keyword is matched case insensitively; every other block name must still be capitalised.
