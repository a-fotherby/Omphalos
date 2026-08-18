"""Lagrangian burial tracking for CrunchTope isotope output."""

import numpy as np
import xarray as xr
from pathlib import Path


def burial_track(results_path, burial_rate_cm_yr, variables):
    """
    Build Lagrangian burial tracks for multiple variables simultaneously.

    Converts Eulerian fields δ(time, depth) to a Lagrangian representation
    δ(cohort_time, burial_age), following sediment parcels as they are buried.

      cohort_time  — simulation time when a parcel was at the sediment surface.
      burial_age   — elapsed time since a parcel was at the surface
                     (= depth / burial_rate at any instant).

    The value at (cohort_time=t_c, burial_age=Δt) is the quantity for the parcel
    that reached the surface at t_c, sampled when it has been buried for Δt years.

    With a single time snapshot the function returns a quasi-steady-state burial
    record, relabelling depth as burial age. This is only valid when the
    simulation time exceeds the domain transit time (domain_length / burial_rate).

    Parameters
    ----------
    results_path : str or Path
        Path to results.nc.
    burial_rate_cm_yr : float
        Solid-phase burial rate in cm/yr (the erode_x value from the
        EROSION/BURIAL block).
    variables : dict
        Mapping of {variable_name: group_name}, e.g.
        {'CO2(aq)': 'toperatio_aq', 'O2(aq)': 'conc'}.
        All variables must have identical time and X coordinates.

    Returns
    -------
    xarray.Dataset
        All variables on dims (file_num, cohort_time, burial_age).
        NaN outside the valid region — where burial_age + cohort_time exceeds
        the simulation end time, or where burial depth exceeds the domain.
    """
    results_path = Path(results_path)

    # Use first variable to establish the shared time/space grid
    first_var, first_group = next(iter(variables.items()))
    ref_ds = xr.open_dataset(results_path, group=first_group)
    ref_da = ref_ds[first_var].isel(Y=0, Z=0)

    times = ref_da.coords['time'].values
    x_vals = ref_da.coords['X'].values
    x_max = float(x_vals[-1])
    burial_ages = x_vals / burial_rate_cm_yr
    n_f = ref_da.sizes['file_num']

    if len(times) == 1:
        # Steady-state: depth profile relabelled as burial age.
        data_vars = {}
        for var_name, group in variables.items():
            ds = xr.open_dataset(results_path, group=group)
            da = (
                ds[var_name].isel(Y=0, Z=0, time=0)
                            .assign_coords(X=burial_ages)
                            .rename({'X': 'burial_age'})
                            .assign_coords(file_num=np.arange(n_f))
                            .expand_dims({'cohort_time': [float(times[0])]})
                            .transpose('file_num', 'cohort_time', 'burial_age')
            )
            data_vars[var_name] = da

        result = xr.Dataset(data_vars)
        result.coords['burial_age'].attrs.update({'units': 'years', 'long_name': 'Burial age'})
        result.coords['cohort_time'].attrs.update({'units': 'years', 'long_name': 'Deposition time'})
        return result

    # Multi-timestep: build a (cohort_time × burial_age) sampling grid once
    # and reuse it for every variable.
    n_c, n_b = len(times), len(burial_ages)

    tc_grid, ba_grid = np.meshgrid(times, burial_ages, indexing='ij')  # (n_c, n_b)
    t_sample = tc_grid + ba_grid            # simulation time at each grid point
    x_sample = ba_grid * burial_rate_cm_yr  # depth at each grid point

    valid = (t_sample <= times[-1]) & (x_sample <= x_max)

    # DataArray indexers sharing a dim → pointwise interpolation in xarray
    t_flat = xr.DataArray(t_sample.ravel(), dims='pts')
    x_flat = xr.DataArray(x_sample.ravel(), dims='pts')

    data_vars = {}
    for var_name, group in variables.items():
        ds = xr.open_dataset(results_path, group=group)
        da = ds[var_name].isel(Y=0, Z=0)  # (file_num, time, X)
        sampled = da.interp(time=t_flat, X=x_flat)  # (file_num, pts)
        values = sampled.values.reshape(n_f, n_c, n_b)
        values[:, ~valid] = np.nan
        data_vars[var_name] = xr.DataArray(values, dims=['file_num', 'cohort_time', 'burial_age'])

    result = xr.Dataset(
        data_vars,
        coords={
            'file_num': np.arange(n_f),
            'cohort_time': times,
            'burial_age': burial_ages,
        },
    )
    result.coords['cohort_time'].attrs.update({'units': 'years', 'long_name': 'Deposition time'})
    result.coords['burial_age'].attrs.update({'units': 'years', 'long_name': 'Time since deposition'})
    return result


def fix_at_deposition(burial_ds, variable):
    """
    Return the value of a variable at the moment of deposition (burial_age = 0).

    Extracts the value at the shallowest point in the domain for each
    (file_num, cohort_time), representing the isotope signature a parcel
    carries when it first enters the sediment.

    Parameters
    ----------
    burial_ds : xarray.Dataset
        Output of burial_track().
    variable : str
        Variable name to extract.

    Returns
    -------
    xarray.DataArray with dims (file_num, cohort_time).
    """
    return burial_ds[variable].isel(burial_age=0)


def fix_at_oxic_anoxic(burial_ds, d13c_var='CO2(aq)', o2_var='O2(aq)', threshold=10e-6):
    """
    Return δ¹³C fixed at the oxic-anoxic boundary.

    For each (file_num, cohort_time), finds the first burial_age at which O₂
    drops below threshold and returns the δ¹³C value at that point. Parcels
    that never become anoxic within the domain return NaN.

    Parameters
    ----------
    burial_ds : xarray.Dataset
        Output of burial_track(), must contain both d13c_var and o2_var.
    d13c_var : str
        Name of the carbon isotope variable (default 'CO2(aq)').
    o2_var : str
        Name of the oxygen variable (default 'O2(aq)').
    threshold : float
        O₂ concentration below which sediment is considered anoxic, in mol/L.
        Default is 10 µmol/L (10e-6 mol/L).

    Returns
    -------
    xarray.Dataset with variables:
        - d13c_var      : δ¹³C at the oxic-anoxic boundary, dims (file_num, cohort_time).
        - 'fix_burial_age' : burial age at the boundary in years, same dims.
    """
    o2 = burial_ds[o2_var]    # (file_num, cohort_time, burial_age)
    d13c = burial_ds[d13c_var]

    anoxic = o2 < threshold
    ever_anoxic = anoxic.any(dim='burial_age')  # (file_num, cohort_time)

    # argmax on bool returns index of first True; 0 if no True exists
    fix_idx = anoxic.values.argmax(axis=-1)  # (file_num, cohort_time), int

    # Build DataArray indexer for advanced isel
    leading_dims = [d for d in d13c.dims if d != 'burial_age']
    leading_coords = {d: d13c.coords[d] for d in leading_dims if d in d13c.coords}
    fix_idx_da = xr.DataArray(fix_idx, dims=leading_dims, coords=leading_coords)

    d13c_fixed = d13c.isel(burial_age=fix_idx_da).where(ever_anoxic)

    fix_burial_age = xr.DataArray(
        np.where(ever_anoxic.values, burial_ds.coords['burial_age'].values[fix_idx], np.nan),
        dims=leading_dims,
        coords=leading_coords,
        attrs={'units': 'years', 'long_name': 'Burial age at oxic-anoxic boundary'},
    )

    return xr.Dataset({d13c_var: d13c_fixed, 'fix_burial_age': fix_burial_age})
