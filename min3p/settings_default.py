# Put the full path to your MIN3P executable here, then remove the _default
# from this file name (-> min3p/settings.py). install.sh can also write this
# file for you. If min3p/settings.py is absent, run.py falls back to a built-in
# default, and the binary can always be overridden per run via the config key
# `min3p_binary`.
min3p_binary = '/path/to/MIN3P/executable'

# Optional. Root of the MIN3P examples/benchmarks tree. Only tests use it: the
# round-trip tests in tests/unit/test_min3p.py parse the real benchmark decks,
# and skip if they cannot be found. The MIN3P_EXAMPLES environment variable
# takes precedence over this.
# min3p_examples = '/path/to/MIN3P/Examples'
