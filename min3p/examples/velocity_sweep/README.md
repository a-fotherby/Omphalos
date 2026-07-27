# MIN3P advective-transport sweep — flow velocity vs driving head

A worked example of the Omphalos MIN3P backend that sweeps a **flow** parameter
(complementing `../dissol_sweep`, which sweeps a chemical boundary condition).

## Problem

`reactran/MCD-2-advection`: a high-pH water (pH 10) is injected into a 1-D column
initially at pH 6. A hydraulic-head gradient between the inflow (head = 1.0 m)
and outflow boundaries drives the water through by advection. The sweep varies
the **outflow-boundary head** over four values `[0.99, 0.97, 0.94, 0.90]`, which
sets the gradient — and hence the Darcy velocity — and shows how far the pH
front migrates.

## Contents

| File | What it is |
|------|-----------|
| `velocity_sweep.yaml` | Sweep config: 4 runs varying the outflow-boundary hydraulic head |
| `velocity_sweep.ipynb` | Reads `results.nc` and plots (A) the migrating pH front, (B) Darcy velocity vs head gradient |
| `velocity_sweep.png` | The figure produced by the notebook |
| `results.nc`, `records.pkl` | Sweep output (git-ignored; regenerable) |

## Reproduce

```bash
cd min3p/examples/velocity_sweep
# Run the sweep (needs the MIN3P binary; adjust template/database paths for your machine)
PYTHONPATH=../../.. conda run -n omphalos python -m min3p.main velocity_sweep.yaml records.pkl
# Regenerate the figure / notebook outputs
conda run -n JupyterEnv jupyter nbconvert --to notebook --execute --inplace velocity_sweep.ipynb
```

## The result

- **Transport:** the injected high-pH front penetrates further as the driving
  head gradient increases (front at ~0.5 m for the mildest gradient up to
  near-breakthrough for the steepest, after 40 days).
- **Darcy's law:** the peak Darcy velocity is linear in the head gradient and
  passes through the origin, with slope equal to the medium's hydraulic
  conductivity (≈ 0.0432 m d⁻¹ = 5×10⁻⁷ m s⁻¹) — recovered directly from the
  swept `.vel` output.
