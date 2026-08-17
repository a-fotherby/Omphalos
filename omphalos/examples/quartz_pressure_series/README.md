# Quartz at depth — a database generated at a series of pressures

**Capability shown:** sweeping a setting of the *log K recomputation*, so each run gets a database
computed at its own pressure. Pressure appears in no CrunchTope keyword and in no database row.

The same 1-D quartz column as `quartz_flow_sweep`, at 150 °C, taken from about 1 km down to about
4 km. Quartz solubility rises with pressure — the dependence that drives pressure solution — so the
deeper the column, the more silica the outflowing water carries.

## The sweep

```yaml
database_logk:
  reactions: ['Quartz']
  on_unmatched: 'leave'
  pressure:
    - 'custom'
    - [100.0, 250.0, 400.0, 550.0, 700.0, 850.0, 1000.0]   # bar
```

```bash
rhea quartz_pressure_series.yaml local --compile-inputs
```

Seven runs, about a minute. A recomputation whose settings are all fixed is done once, on the
template; sweeping one moves it to once per run.

## What it produces

Each run's `datacom.dbs` differs from the template on **exactly one line** — the quartz row — with
the column alignment intact:

```
template:  'Quartz'   22.6880  1    1.0000 'SiO2(aq)'   -4.6319  -3.9993  -3.4734  -3.0782  -2.7191 …
run6:      'Quartz'   22.6880  1    1.0000 'SiO2(aq)'   -4.4533  -3.7704  -3.2328  -2.8445  -2.4999 …
```

From 100 to 1000 bar the database predicts **+32.3%** dissolved silica at saturation, and CrunchTope
delivers **+31.7%** at the column outflow — which is the check that the pressure travelled the whole
way, from config to pyGCC to the per-run `.dbs` to the model. The runs sit 1.1–1.5% below
saturation throughout, the residual undersaturation of a fluid still reacting as it leaves.

## The thing to know

**A CrunchTope database has no pressure row.** Its header carries temperature points and
Debye-Hückel coefficients and nothing else, so a file computed at 1000 bar is indistinguishable from
one computed on the water saturation curve, and nothing warns you. The pressure each run used is
therefore recorded beside the run, in `run*/logk_settings.json` and in the `database_logk` group of
`conditions.nc`. `--compile-inputs` is what writes the latter; for a pressure series it is the only
durable record of what was run.

## Two choices worth understanding

**`reactions: ['Quartz']`** recomputes the one reaction this deck's chemistry consists of, which is
exact here and makes the result auditable. A deck with real aqueous speciation wants
`reactions: 'all'` instead: on this database that recomputes 824 reactions, costs about 1.5 s a run,
and introduces no no-data values — it fills in 58 rows the shipped file had left blank.

**`on_unmatched: 'leave'`** keeps the tabulated value for reactions pyGCC does not have. Combined
with `'all'`, that leaves a file part pyGCC and part whatever compiled the original. Not wrong, but
worth knowing rather than discovering.

## Files

| | |
|---|---|
| `quartz_column_deep.in` | the deck — no mention of pressure anywhere |
| `quartz_pressure_series.yaml` | the sweep |
| `datacom.dbs` | the template database, on the water saturation curve |
| `quartz_pressure_series.ipynb` | the analysis, with its outputs stored so it reads without running |
| `quartz_pressure_series.png` | the figure it produces |

Running the sweep adds `run0/ … run6/` — one database, one deck and one CrunchTope run each — plus
`results.nc` and `conditions.nc`. Those are outputs, not inputs, and are not in the repository.

Every pressure stays above the water saturation pressure at 300 °C (85.9 bar), the top of this
database's temperature grid, so pyGCC is never asked for a log K in steam. Below that it returns
NaN, which Omphalos writes as the no-data value 500 and warns about.
