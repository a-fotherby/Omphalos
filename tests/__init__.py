"""Marks the test tree as a package.

Not optional. tests/unit/test_sweep_plots.py takes its fixtures from tests.unit.test_sweep, and
without this file `tests` is merely a namespace package -- which any installed distribution
shipping its own top-level `tests` will shadow, since a regular package always wins. f90nml 1.5.0
ships exactly that, so under pip `tests` resolved into f90nml's copy and the import failed with
"No module named 'tests.unit'". The conda environment escapes it only by pinning f90nml 1.4.4,
which does not ship one.
"""
