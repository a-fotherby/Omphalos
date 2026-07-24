"""Generate a dataset of MIN3P input files from a template + YAML config.

MIN3P input is *positional*: a parameter is identified by its block, the
sub-keyword that owns it, which data line under that sub-keyword, and which
token on that line. Rather than hard-code a semantic name for every parameter
(as the CrunchTope backend can, because its format is key-value), the MIN3P
sweep is driven by an explicit ``modifications`` mapping in the config that
names these coordinates directly. A small :data:`MIN3P_IDs` table provides
convenient aliases for the most common targets.

Config format (see ``example_min3p.yaml``)::

    template: appelo.dat
    number_of_files: 3
    database_directory: /abs/path/to/database/default   # optional, repointed
    timeout: 120
    modifications:
      calcite_volume:
        block: 'initial condition - local geochemistry'
        keyword: 'mineral input'
        line: 0            # optional, default 0
        token: 0           # optional, default 0
        method: linspace   # any core.parameter_methods method
        params: [0.005, 0.02]
"""

import copy

import core.parameter_methods as pm
from min3p.keyword_block import normalise

# Dispatch table for value-array generation (shared with the other backends).
_DISPATCH = {
    'linspace': pm.linspace,
    'random_uniform': pm.random_uniform,
    'constant': pm.constant,
    'custom': pm.custom_list,
    'staged': pm.staged,
}

# Convenience aliases: yaml modification 'alias' -> default (block, keyword,
# line, token) coordinate. A modification entry may set ``alias`` instead of
# spelling out block/keyword. Extend as further blocks are supported.
MIN3P_IDs = {
    'calcite_volume': ('initial condition - local geochemistry', 'mineral input', 0, 0),
    'ph_guess': ('initial condition - local geochemistry', 'guess for ph', 0, 0),
}


def _fmt(value):
    """Format a value as a MIN3P-friendly token string.

    Strings pass through unchanged (e.g. a quoted enumerated value); numerics
    use ``%g`` which MIN3P's Fortran reader accepts (it also reads ``d``/``D``
    exponents, but ``e`` notation is fine on input).
    """
    if isinstance(value, str):
        return value
    return '{:g}'.format(float(value))


def _resolve_block(input_file, block_name):
    """Return the ``Min3pBlock`` for a (possibly non-normalised) block name.

    Raises:
        KeyError: If no matching block exists.
    """
    key = normalise(block_name)
    if key in input_file.keyword_blocks:
        return input_file.keyword_blocks[key]
    raise KeyError(
        f"Block '{block_name}' (normalised '{key}') not found. "
        f"Available blocks: {list(input_file.keyword_blocks)}"
    )


def _coordinates(spec):
    """Resolve a modification spec into (block, keyword, line, token).

    Args:
        spec: The per-modification config dict.

    Returns:
        Tuple ``(block_name, keyword, line_index, token_pos)``.
    """
    if 'alias' in spec:
        block, keyword, line, token = MIN3P_IDs[spec['alias']]
    else:
        block, keyword, line, token = spec['block'], spec['keyword'], 0, 0
    # Explicit fields override alias defaults where provided.
    block = spec.get('block', block)
    if 'keyword' in spec:
        keyword = spec['keyword']
    line = spec.get('line', line)
    token = spec.get('token', token)
    return block, normalise(keyword), line, token


def _value_array(spec, num_files):
    """Build the per-file value array for a modification spec."""
    method = spec['method']
    try:
        func = _DISPATCH[method]
    except KeyError as exc:
        raise ValueError(
            f"Unknown parameter method '{method}'. Valid: {list(_DISPATCH)}"
        ) from exc
    return func(spec['params'], num_files)


def _set_database_directory(input_file, directory):
    """Repoint the 'database directory' entry (needed on non-Windows hosts)."""
    try:
        block = _resolve_block(input_file, 'geochemical system')
    except KeyError:
        return
    if 'database directory' in block.contents and block.contents['database directory']:
        block.modify('database directory', f"'{directory}'", token_pos=0, line_index=0)


def configure_input_files(template, tmp_dir, rhea=False, override_num=-1):
    """Build ``{file_num: InputFile}`` with the config's modifications applied.

    Args:
        template: A parsed :class:`min3p.template.Template`.
        tmp_dir: Working directory (used for parity with other backends; MIN3P
            copies no auxiliary files here at present).
        rhea: Whether running under rhea (parallel). Currently only affects
            whether the database directory copy is left to the caller.
        override_num: If not -1, force every file's ``file_num`` to this value.

    Returns:
        Dict ``{file_num: InputFile}``.
    """
    config = template.config
    num_files = config['number_of_files']
    file_dict = template.make_dict()

    if override_num != -1:
        for f in file_dict:
            file_dict[f].file_num = override_num

    # Precompute value arrays for each modification.
    modifications = config.get('modifications') or {}
    arrays = {name: _value_array(spec, num_files) for name, spec in modifications.items()}

    db_dir = config.get('database_directory')

    for f in file_dict:
        input_file = file_dict[f]
        file_num = input_file.file_num

        if db_dir:
            _set_database_directory(input_file, db_dir)

        for name, spec in modifications.items():
            block_name, keyword, line, token = _coordinates(spec)
            block = _resolve_block(input_file, block_name)
            block.modify(keyword, _fmt(arrays[name][file_num]), token_pos=token, line_index=line)

    return file_dict


# Default coordinate of the final solution time (Data Block 4, positional
# _header line: time-unit, start, FINAL, max-dt, min-dt). Overridable via
# restart_chain.final_time_coord = [block, keyword, line, token].
FINAL_TIME_COORD = ['time step control - global system', '_header', 2, 0]


def configure_staged_input_files(template, tmp_dir, rhea=False):
    """Build a restart chain: ``{run_num: {stage_num: InputFile}}``.

    Each run is a sequence of stages that continue one another via MIN3P's
    restart mechanism. Stage 0 is the base input (with the config's
    ``modifications`` applied); each later stage additionally enables
    ``'restart'`` (+ an append mode) in the global-control block and sets its own
    final solution time, so re-running it in the same directory (after the
    latest ``restart.tmp`` is copied to ``restart.dat`` -- handled by
    ``run.run_staged``) continues from the previous stage's end time.

    Config (``restart_chain`` block)::

        restart_chain:
          stages: 3
          final_times: [100.0, 200.0, 400.0]   # per-stage final solution time
          append: 'append results'             # or 'append results in legacy mode' / null
          final_time_coord: [block, keyword, line, token]   # optional override

    Args:
        template: Parsed :class:`min3p.template.Template`.
        tmp_dir: Working directory (parity with other backends).
        rhea: Whether running under rhea.

    Returns:
        Nested dict ``{run_num: {stage_num: InputFile}}``.
    """
    import copy

    config = template.config
    num_files = config['number_of_files']
    rc = config['restart_chain']
    num_stages = rc['stages']
    final_times = rc.get('final_times')
    append_mode = rc.get('append', 'append results')
    coord = rc.get('final_time_coord', FINAL_TIME_COORD)

    if final_times is not None and len(final_times) != num_stages:
        raise ValueError(
            f"restart_chain.final_times has {len(final_times)} entries but "
            f"stages={num_stages}; they must match."
        )

    # Base per-run files with the config's modifications already applied.
    base = configure_input_files(template, tmp_dir, rhea=rhea)

    staged = {}
    for run_num in range(num_files):
        staged[run_num] = {}
        for stage in range(num_stages):
            f = copy.deepcopy(base[run_num])
            f.stage_num = stage

            if final_times is not None:
                bname, keyword, line, token = coord
                block = _resolve_block(f, bname)
                key = '_header' if keyword == '_header' else normalise(keyword)
                block.modify(key, _fmt(final_times[stage]), token_pos=token, line_index=line)

            if stage > 0:
                gc = _resolve_block(f, 'global control parameters')
                gc.add_keyword('restart')
                if append_mode:
                    gc.add_keyword(append_mode)

            staged[run_num][stage] = f

    return staged


def evaluate_config(config):
    """Return the per-modification value arrays for ``config`` (without applying).

    Provided for parity/testing; :func:`configure_input_files` computes these
    internally.
    """
    num_files = config['number_of_files']
    modifications = config.get('modifications') or {}
    return {name: _value_array(spec, num_files) for name, spec in modifications.items()}
