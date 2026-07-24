# MIN3P reactive-transport sweep — calcite dissolution

A worked example of the Omphalos MIN3P backend: a parameter sweep over the
`reactran/dissol` benchmark (1-D calcite dissolution during transport) and a
notebook that reads and plots the results.

## Contents

| File | What it is |
|------|-----------|
| `dissol_sweep.yaml` | Sweep config: 4 runs varying the inflow acidity (free H⁺ at the inflow boundary) |
| `dissol_sweep.ipynb` | Reads `results.nc` and plots the dissolution front (Ca²⁺, pH, calcite volume fraction vs depth) |
| `dissol_sweep.png` | The figure produced by the notebook |
| `results.nc` | Sweep output — one netCDF group per MIN3P output category |
| `records.pkl` | Pickled `InputFile` records for the run |

## Reproduce

```bash
cd min3p/examples/dissol_sweep
# 1. Run the sweep (writes results.nc + records.pkl). Needs the MIN3P binary and
#    the repo on PYTHONPATH; adjust the template/database paths in the YAML for
#    your machine.
PYTHONPATH=../../.. conda run -n omphalos python -m min3p.main dissol_sweep.yaml records.pkl

# 2. Regenerate the figure / notebook outputs (any env with xarray + matplotlib).
conda run -n JupyterEnv jupyter nbconvert --to notebook --execute --inplace dissol_sweep.ipynb
```

## The result

As the injected water becomes more acidic, calcite near the inlet is consumed
(its volume fraction collapses to the numerical floor), the low-pH front breaks
through instead of being buffered, and a Ca²⁺ pulse is released at the migrating
dissolution front. The two mildest inflow waters stay calcite-buffered
(pH ≈ 8–10, calcite intact); the two most acidic exhaust the calcite near the
inlet and the acid front penetrates the column.
