"""MIN3P-THCm backend for Omphalos.

Mirrors the ``omphalos`` (CrunchTope) and ``pflotran`` backends, providing a
``Template``/``InputFile`` model for MIN3P ``.dat`` input files, a TecPlot output
parser, and glue for parameter sweeps via ``generate_inputs`` and ``run``.

See ``min3p/examples/dissol_sweep/`` for a runnable worked example.
"""
