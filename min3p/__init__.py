"""MIN3P-THCm backend for Omphalos.

Mirrors the ``omphalos`` (CrunchTope) and ``pflotran`` backends, providing a
``Template``/``InputFile`` model for MIN3P ``.dat`` input files, a TecPlot output
parser, and glue for parameter sweeps via ``generate_inputs`` and ``run``.

See ``MIN3P_integration_notes.md`` in the project root for the design rationale
and the verified file-format details this module relies on.
"""
