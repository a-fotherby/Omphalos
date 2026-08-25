"""Methods to handle invoking CrunchTope on an InputFile object."""

import subprocess
import sys
from pathlib import Path

import numpy as np
import pexpect as pexp
import xarray as xr

from core import spatial_constructor as sc
import core.keyword_block as kb
from core.file_methods import data_cats
from core.keyword_block import SNAPSHOT_TIME_KEYWORDS, snapshot_times
import omphalos.crunch_keywords as ck
from omphalos.settings import crunch_dir

# Where a per-run log K recomputation records the settings it used. CrunchTope neither reads nor
# minds it; it exists because the database cannot say what pressure it was computed at.
LOGK_RECORD = 'logk_settings.json'

# A floating-point NaN as CrunchTope prints one, in a numeric field.
NAN_PATTERN = r'[\s,=(][-+]?NaN[\s,)]'

# Error patterns searched in CrunchTope stdout. pexpect compiles these as regular expressions and
# returns the index of the first match, so more specific strings should come before generic ones.
CT_ERROR_PATTERNS = [
    # Startup failure: CrunchTope cannot find the input file and then blocks on stdin, so without
    # this pattern the run sits until the configured timeout with no indication of why. Two causes:
    # a path with a space in it, since the command string is split on whitespace before CrunchTope
    # sees it, and a path long enough to overrun CrunchTope's fixed-length buffer. Passing only the
    # basename (see `crunchtope`) avoids both, but a deck named from elsewhere can still hit them.
    'Cannot find input file',
    # A 2-D or 3-D problem with 'hindmarsh true'. CrunchTope reports that it cannot use the
    # Hindmarsh block tridiagonal solver, says it is switching to PETSc, and then waits on stdin
    # ('Return to continue'). pexpect gives the child a pty, so that read blocks and the run burns
    # its entire timeout having produced nothing. Matched on the prompt rather than the solver
    # message because it is the prompt that does the blocking.
    'Return to continue',
    # A FLOW zone entry missing its K range, as in 'pressure 0.0 zone 43-43 1-42 fix'. CrunchTope
    # prints this and exits, which is worse than hanging: pexpect sees EOF, the run is recorded as
    # a success, and get_results goes on to parse a directory containing no tecplot output at all.
    # Exercise17, Exercise18 and Exercise19 of the short course all ship decks that hit this.
    # Matched on the substring, as the timeseries case below is, because CrunchTope reports whichever
    # axis is missing: Exercise19 prints the Y wording, and the literal 'No Z location for pressure'
    # let it through to be recorded as a success with no output.
    'location for pressure',
    # A time_series entry giving only an X node in a 2-D or 3-D problem: 'time_series out.dat 251'
    # wants a Y index too, as 'time_series_at_node out.dat 30 30' has. CrunchTope exits, so this is
    # the same false success as the pressure case above. Matched on the substring so that the Y and
    # Z wordings are both caught.
    'location for timeseries must be specified',
    # A database reaction whose components are not all present in the basis. CrunchTope prints the
    # offending secondary species or mineral and then blocks on stdin, so this is a hang rather than
    # an exit. It used to be caught only by the 'NaN' pattern below, and only by luck: the species
    # that tripped it happened to be named NaNO3(aq). Any other name and the run burned its whole
    # timeout with the cause sitting in plain text on stdout.
    'species missing in reaction',
    'EXCEEDED MAXIMUM ITERATIONS',
    'TRY A',
    'divide by zero',
    # The bare substring 'NaN' matched chemical names too -- NaNO3(aq) and NaNpO2CO3.3.5H2O are in
    # every database the short course ships -- so a run could be failed for a species name appearing
    # on stdout. Requiring a delimiter on both sides keeps a printed number and rejects a name, since
    # what follows the 'NaN' in both of those is a letter. Deliberately un-anchored: pexpect searches
    # a stream buffer, so '^' and '$' would refer to wherever that buffer happens to begin and end
    # rather than to the start and end of a line.
    NAN_PATTERN,
    # --- Refusals the newer CrunchTope releases print and older ones do not.
    #
    # Every pattern above was derived against BOGLSource2026, which is a CrunchTope 1.x derivative
    # closest to upstream v2.0.0. Upstream v2.10 and v3.0 added fatal checks, and each of them prints a
    # message and then blocks on stdin -- so left unmatched they cost a run its entire timeout and are
    # recorded as a timeout rather than as the thing that actually went wrong. Checked against six
    # known-good run logs across three builds for false positives before being added.
    #
    # v3.0 (upstream 56731f1, 2024-11-22) made H2O mandatory. Every deck written before that needs
    # 'H2O' in PRIMARY_SPECIES and 'H2O 55.50843506' in each condition.
    'H2O must be present',
    # v2.10 retired the .ant control files; v3.0 and master retired the Hellmann rate law and several
    # named options (KateMaher, Nuft). Both wordings appear.
    'no longer used',
    'no longer supported',
    # v3.0 stopped falling back to a default database name.
    'No default database exists',
    'Ionic strength cannot be zero',
    # Covers the tempreg filename and region count, the transpiration cell count, the pump units and
    # the time-series region ID -- all v3.0 additions sharing one wording.
    'must be provided',
    'unit for space must be',
    # A zone entry giving fewer coordinates than the build expects. BOGLSource2026 accepts an X range
    # alone in INITIAL_CONDITIONS ('initial 1-100'); v2.0.0 onward want every axis.
    'grid location should follow',
    'Zero length string',
    # An auxiliary file the deck names but which was never staged into the run directory.
    'file not found',
    # Nucleation: an unresolved substrate mineral, and a nucleation rate law in the database with no
    # NUCLEATION block to configure it from.
    'not found in list',
    'rate law found listed in database',
    'forrtl:',            # Fortran runtime error prefix
    'Segmentation fault',
    'Killed',
    'FATAL',
]

# What to call a pattern in the failure message, where the pattern itself is a regex and so would
# not read as anything. Patterns absent from here are printed as they are written.
CT_ERROR_LABELS = {NAN_PATTERN: 'NaN in a printed value'}

# error_code for a run that ended cleanly but wrote no output. Negative so that it can never collide
# with an index into CT_ERROR_PATTERNS as that list grows.
NO_OUTPUT_ERROR_CODE = -1

# Values CrunchTope's read_logical accepts as true.
_TRUE_TOKENS = ('true', 'yes', 'on', 't', 'y')


def _expects_tecplot_output(input_file):
    """Whether this deck asked CrunchTope for tecplot snapshots.

    Most of CrunchTope's several hundred fatal paths print a message and then simply STOP. pexpect
    sees EOF, which is indistinguishable from a clean finish, so the run used to be recorded as a
    success and then parsed for output that was never written. Knowing whether output was expected is
    what makes an empty run directory diagnostic.

    Two kinds of deck legitimately write nothing and must not be failed: one running
    ``speciate_only``, and one with no snapshot times, which CrunchTope reports as 'Timestepping
    off--initialization only'.

    Args:
        input_file: The InputFile whose keyword blocks were read.

    Returns:
        True only if snapshot output can be positively confirmed as expected. Anything unreadable
        returns False, since wrongly failing a good run is worse than missing a bad one.
    """
    try:
        blocks = input_file.keyword_blocks
        runtime = blocks['RUNTIME'].contents if 'RUNTIME' in blocks else {}
        if str(runtime.get('speciate_only', ['false'])[0]).lower() in _TRUE_TOKENS:
            return False

        if 'OUTPUT' not in blocks:
            return False
        times = kb.snapshot_times(blocks['OUTPUT'].contents)
        # 'Timestepping turned on, but no time provided' -- CrunchTope only initialises.
        return any(float(t) > 0 for t in times)
    except (AttributeError, KeyError, TypeError, ValueError):
        return False


def _get_kinetic_db_name(input_file):
    """Get the kinetic database filename from RUNTIME block.

    CrunchTope 1.x spells this keyword 'kinetic_database' and 2+ spells it 'aqueousdatabase'. Both
    are read here, because this only needs the filename, and which spelling the configured binary
    actually understands is checked once per sweep by crunch_keywords.check_deck.

    Args:
        input_file: InputFile object with parsed keyword blocks.

    Returns:
        str: Kinetic database filename, or None if not found.
    """
    runtime_contents = input_file.keyword_blocks['RUNTIME'].contents
    keyword = ck.deck_keywords(runtime_contents).get('aqueous')

    return runtime_contents[keyword][0] if keyword else None


def _get_catabolic_file_name(input_file):
    """Get the catabolic pathways filename from the RUNTIME block.

    Args:
        input_file: InputFile object with parsed keyword blocks.

    Returns:
        str: The filename the deck names, or CrunchTope's default where it names none.
    """
    runtime_contents = input_file.keyword_blocks['RUNTIME'].contents
    keyword = ck.deck_keywords(runtime_contents).get('catabolic')

    if not keyword:
        return ck.DEFAULT_CATABOLIC_FILE

    return runtime_contents[keyword][0] or ck.DEFAULT_CATABOLIC_FILE


def _get_database_name(input_file):
    """Get the thermodynamic database filename from the RUNTIME block.

    Args:
        input_file: InputFile object with parsed keyword blocks.

    Returns:
        str: Database filename, or None if the deck does not name one.
    """
    return input_file.keyword_blocks['RUNTIME'].contents.get('database', [None])[0]


def _print_aux_files(input_file, tmp_path):
    """Write auxiliary database and pathway files to the run directory.

    Every execution path -- sequential, rhea non-staged and staged restart -- comes through here, so
    a swept database written at this one point reaches all three. rhea/prep_directories.sh has
    already copied the template's database in; an edited one overwrites it under the same name.

    A per-run log K recomputation is written out beside the database as LOGK_RECORD. It has to be:
    a CrunchTope database has no pressure row, so the file this writes is byte-comparable between a
    run at 500 bar and one at saturation, and rhea's worker rebuilds its InputFile from the run
    directory rather than from the object that carried the settings. Without the sidecar the
    pressure would be gone by the time anything came to record it.
    """
    record_path = Path(tmp_path) / LOGK_RECORD

    if getattr(input_file, 'logk_settings', None):
        import json

        with open(record_path, 'w') as record:
            json.dump(input_file.logk_settings, record, indent=2, sort_keys=True)
    elif record_path.exists():
        # rhea/prep_directories.sh does `mkdir run$N` and never clears it, so a directory reused by
        # a later sweep keeps whatever the last one left. A sidecar from a sweep that varied the
        # pressure would otherwise be read back as this run's, and recorded as a pressure that never
        # applied. Nothing swept means there is nothing to record.
        record_path.unlink()

    if input_file.aqueous_database:
        kinetic_db = _get_kinetic_db_name(input_file)
        if kinetic_db:
            input_file.aqueous_database.print(str(tmp_path / kinetic_db))
    if input_file.catabolic_pathways:
        input_file.catabolic_pathways.print(str(tmp_path / _get_catabolic_file_name(input_file)))
    if input_file.database is not None:
        database_name = _get_database_name(input_file)
        if database_name:
            input_file.database.print(str(tmp_path / database_name))


def run_dataset(file_dict, tmp_dir, timeout):
    """Run all input files in the dataset.

    Args:
        file_dict: Dictionary of InputFile objects
        tmp_dir: Temporary directory for output files
        timeout: Timeout in seconds for each simulation

    Returns:
        Updated file_dict with results
    """
    for file_num, entry in enumerate(file_dict):
        file_dict[entry] = input_file(file_dict[entry], file_num, tmp_dir, timeout)

    return file_dict


def input_file(input_file, file_num, tmp_dir, timeout):
    """Run a single input file through CrunchTope.

    Args:
        input_file: InputFile object to run
        file_num: File number for logging
        tmp_dir: Temporary directory for output
        timeout: Timeout in seconds

    Returns:
        Updated InputFile with results
    """
    tmp_path = Path(tmp_dir).resolve()

    input_file.path = tmp_path / input_file.path
    input_file.print()

    if input_file.later_inputs:
        for name in input_file.later_inputs:
            input_file.later_inputs[name].path = tmp_path / input_file.later_inputs[name].path
            input_file.later_inputs[name].print()

    _print_aux_files(input_file, tmp_path)

    crunchtope(input_file, file_num, timeout, tmp_path)

    return input_file


def _terminate(process):
    """Kill a CrunchTope child that matched an error pattern or timed out.

    Several of the patterns above are printed by a CrunchTope that then waits on stdin, and pexpect
    gives the child a pty, so the read blocks indefinitely. Matching the pattern is only half the
    job: without this the process stays resident for the rest of the sweep, and on a run of any size
    those accumulate one per failed file.
    """
    try:
        process.close(force=True)
    except Exception as exc:                       # noqa: BLE001 - never fail a run over cleanup
        print(f'Could not close CrunchTope process: {exc}')


def crunchtope(input_file, file_num, timeout, tmp_dir, file_offset=0):
    """Execute CrunchTope on an input file.

    Args:
        input_file: InputFile object to run
        file_num: File number for logging
        timeout: Timeout in seconds
        tmp_dir: Working directory (Path object)
        file_offset: Offset for TecPlot file numbering (used in staged restarts).
    """
    # Name only, not the path: pexpect splits the command string on whitespace, so an absolute
    # path containing a space reaches CrunchTope truncated at the first one -- it reports
    # 'Cannot find input file' and blocks on stdin until the timeout. A long path can also
    # overrun CrunchTope's own fixed-length buffer. The deck always sits directly in tmp_dir and
    # pexpect is already given cwd=tmp_dir, so the basename resolves and is the shortest form.
    command = f'{crunch_dir} {Path(input_file.path).name}'
    process = pexp.spawn(command, timeout=timeout, cwd=str(tmp_dir), encoding='latin-1')
    process.logfile = sys.stdout

    expect_list = [pexp.EOF, pexp.TIMEOUT] + CT_ERROR_PATTERNS
    error_code = process.expect(expect_list)

    if error_code == 0:
        # EOF alone does not mean success: most of CrunchTope's fatal paths print a message and STOP,
        # which looks identical from here. If the deck asked for snapshots and none were written, the
        # run failed however cleanly it exited.
        if _expects_tecplot_output(input_file) and not data_cats(str(tmp_dir)):
            print(f'File {file_num} exited without writing any tecplot output; '
                  'check its .out file for a CrunchTope error message.')
            input_file.error_code = NO_OUTPUT_ERROR_CODE
        else:
            input_file.get_results(str(tmp_dir), file_offset=file_offset)
            print(f'File {file_num} outputs recorded.')
    elif error_code == 1:
        print(f'File {file_num} timed out.')
        input_file.error_code = error_code
        _terminate(process)
    else:
        pattern = CT_ERROR_PATTERNS[error_code - 2]
        print(f'Error in file {file_num}: "{CT_ERROR_LABELS.get(pattern, pattern)}".')
        input_file.error_code = error_code
        _terminate(process)

    print(f'File {file_num} complete.')

    return input_file


def clean_dir(tmp_dir, file_name):
    """Clean up temporary files from a directory.

    Args:
        tmp_dir: Directory to clean
        file_name: Specific file to remove
    """
    tmp_path = Path(tmp_dir)
    subprocess.run(['rm', "*.tec"], cwd=str(tmp_path))
    subprocess.run(['rm', "*.out"], cwd=str(tmp_path))
    subprocess.run(['rm', file_name], cwd=str(tmp_path))


def stage_zones(stage_file):
    """The xzones tokens a stage declares, or None if it declares none.

    Returns the tokens rather than just the cell count because a graded grid -- coarse at the top,
    fine through the interval of interest, coarse again at the bottom -- needs the widths as well:
    without them the resample maps by cell index instead of by position.
    """
    discretization = stage_file.keyword_blocks.get('DISCRETIZATION')
    if discretization is None:
        return None

    return discretization.contents.get('xzones')


def stage_nx(stage_file):
    """Number of grid cells a stage's input file discretises the column into.

    Returns None if the stage declares no xzones, in which case a chain cannot know whether the
    grid changed and will not try to regrid.
    """
    zones = stage_zones(stage_file)

    return sc.zone_cell_count(zones) if zones else None


def _porosity_profile(stage_file, nx):
    """The porosity a stage's deck reads from file, or None if it reads none.

    A restart overrides the deck -- ``CALL restart`` runs after ``CALL StartTope`` -- so a porosity
    resampled from the coarse grid would supersede this stage's read_PorosityFile. Handing the
    intended values back lets the regrid write them into the restart file instead.

    The file is a column of values, or two columns with the porosity second, as
    read_PorosityFile accepts.
    """
    porosity_block = stage_file.keyword_blocks.get('POROSITY')
    if porosity_block is None:
        return None

    for keyword, entry in porosity_block.contents.items():
        # CrunchTope matches the keyword case insensitively and the parser keeps whatever spelling
        # the deck used, so neither spelling can be assumed.
        if keyword.lower() != 'read_porosityfile' or not entry:
            continue

        name = entry[0]
        try:
            table = np.loadtxt(name)
        except OSError as error:
            print(f'Warning: could not read porosity file "{name}" ({error.strerror}); the restart '
                  'file keeps the porosity resampled from the previous stage.')
            return None

        column = table[:, 1] if table.ndim == 2 else table
        if len(column) < nx:
            print(f'Warning: {name} has {len(column)} rows but the stage has {nx} cells; the '
                  'restart file keeps the porosity resampled from the previous stage.')
            return None

        return column[:nx]

    return None


def regrid_between_stages(stages_dict, stage_num, tmp_dir):
    """Resample the restart file the previous stage wrote onto this stage's grid.

    Returns early when the two stages agree on nx, so a chain that does not change resolution is
    untouched. The source file's layout is verified first: a byte-identical nx -> nx round trip is
    cheap and proves the parse was understood before anything is overwritten.

    The result is written to whatever file this stage's deck names in its ``restart`` directive,
    which ``generate_inputs`` gives a distinct, cell-count-bearing name precisely so the previous
    stage's output survives at the resolution its own name advertises. A deck naming the same file
    for both -- a hand-written chain, or one generated before that change -- still gets the old
    replace-in-place behaviour.

    Args:
        stages_dict: Dict mapping stage_num to InputFile for this run.
        stage_num: The stage about to run, which must be greater than zero.
        tmp_dir: Directory the stages run in, where the restart file was written.

    Returns:
        bool: True if a regrid was performed.
    """
    from omphalos import restart_file as rf

    previous, current = stages_dict[stage_num - 1], stages_dict[stage_num]
    zones_in, zones_out = stage_zones(previous), stage_zones(current)
    nx_in, nx_out = stage_nx(previous), stage_nx(current)

    if zones_in is None or zones_out is None or zones_in == zones_out:
        # Identical zone specifications mean an identical grid, including a graded one, so there is
        # nothing to resample. Comparing cell counts alone would miss a chain that keeps nx and
        # redistributes the cells, which does need a regrid.
        return False

    restart_name = previous.keyword_blocks['RUNTIME'].contents.get('save_restart')
    if not restart_name:
        raise rf.RstError(
            f'stage {stage_num - 1} changes grid from {nx_in} to {nx_out} cells but writes no '
            'restart file, so there is nothing for the next stage to start from'
        )

    path = Path(tmp_dir) / restart_name[0]
    dims = rf.dims_from_input_file(previous)

    # Where the regridded file goes: this stage reads it, so the deck's own restart directive is
    # the authority on its name. Falling back to the source keeps decks that predate the distinct
    # naming working unchanged.
    read_name = (current.keyword_blocks['RUNTIME'].contents.get('restart') or [None])[0]
    destination = Path(tmp_dir) / read_name if read_name else path

    if not rf.verify_identity(path, nx_in, dims):
        raise rf.RstError(
            f'{path.name} does not round-trip at nx={nx_in}, so its layout is not understood. '
            'Refusing to regrid: the result would be a plausible file with its fields misaligned.'
        )

    inject = {}
    porosity = _porosity_profile(current, nx_out)
    if porosity is not None:
        inject['por'] = porosity

    into = '' if destination == path else f' into {destination.name}'
    print(f'Regridding {path.name} from {nx_in} to {nx_out} cells for stage {stage_num}{into}.')
    regridded = destination.with_suffix(destination.suffix + '.regrid.tmp')
    try:
        _, rewritten = rf.regrid(path, nx_in, nx_out, regridded, dims, inject=inject,
                                 deck=Path(current.path) if current.path else None,
                                 zones_in=zones_in, zones_out=zones_out)
        regridded.replace(destination)
    finally:
        regridded.unlink(missing_ok=True)

    if rewritten:
        print(f'  re-derived for consistency: {", ".join(rewritten)}')
    if inject:
        print(f'  injected porosity from the stage {stage_num} deck')

    return True


def _spinup_file_offset(stage_file, tmp_path):
    """Return the tecplot file number stage 0's first output will actually carry, minus one.

    A chain whose stage 0 restarts from a spinup does not begin its output at ``*1.tec``:
    ``restart.F90`` restores ``nint`` and CrunchTope writes that number on the files, so
    parsing would look for outputs that were never written and find nothing to concatenate.

    Args:
        stage_file: The stage 0 InputFile or Template, already carrying its restart directive.
        tmp_path: Directory the run executes in, where the restart file was staged.

    Returns:
        int: The offset to seed ``file_offset`` with; 0 when stage 0 starts cold.
    """
    from omphalos import restart_file as rf

    runtime = stage_file.keyword_blocks.get('RUNTIME')
    restart = (getattr(runtime, 'contents', None) or {}).get('restart') if runtime else None
    if not restart:
        return 0

    path = Path(tmp_path) / restart[0]
    if not path.is_file():
        # rhea stages the file, so a miss here means CrunchTope will fail on it anyway.
        print(f'Warning: stage 0 restarts from "{restart[0]}", which is not in the run '
              'directory. Output file numbering assumes it starts at 1.')
        return 0

    try:
        return max(0, int(rf.stored_counters(path)['nint']) - 1)
    except (rf.RstError, OSError) as error:
        print(f'Warning: could not read the output counter from "{restart[0]}" ({error}). '
              'Output file numbering assumes stage 0 starts at 1.')
        return 0


def run_staged_input(stages_dict, run_num, tmp_dir, timeout):
    """Run stages sequentially for a single parallel run.

    Staged input files are already printed by rhea/main.py, so this function
    only runs CrunchTope on them sequentially and collects results.

    Args:
        stages_dict: Dict mapping stage_num to InputFile for this run.
        run_num: The parallel run number.
        tmp_dir: Temporary directory for running input files.
        timeout: Timeout for CrunchTope execution.

    Returns:
        InputFile: The first stage InputFile with concatenated results from all stages.
    """
    tmp_path = Path(tmp_dir)
    num_stages = len(stages_dict)

    # Stage 0 starts its output at file 1 unless it restarts from a spinup, in which case
    # CrunchTope continues the numbering from the counter stored in that file.
    file_offset = _spinup_file_offset(stages_dict[0], tmp_path)

    for stage_num in range(num_stages):
        stage_file = stages_dict[stage_num]

        # Every stage writes its own auxiliary files. A 'staged' sweep of database_parameters or
        # namelists gives each stage different ones, and CrunchTope reads them from the run
        # directory under the name the deck uses, so they have to be refreshed before each stage
        # runs. Writing them for stage 0 alone left every later stage running against stage 0's.
        _print_aux_files(stage_file, tmp_path)

        if stage_num > 0:
            # A .rst carries no grid metadata, so a stage that changes xzones fails on its first
            # array read unless the file is resampled first.
            regrid_between_stages(stages_dict, stage_num, tmp_path)

        print(f'Running run {run_num}, stage {stage_num}')
        crunchtope(stage_file, run_num, timeout, tmp_path, file_offset=file_offset)

        output_contents = stage_file.keyword_blocks['OUTPUT'].contents
        if any(key in output_contents for key in SNAPSHOT_TIME_KEYWORDS):
            file_offset += len(snapshot_times(output_contents))

        if stage_file.error_code != 0:
            print(f'Error in run {run_num}, stage {stage_num}. Stopping staged execution.')
            break

    host = concat_staged_results(stages_dict)

    return stages_dict[host]


def snap_to_grid(dataset, target_x):
    """Place a dataset's cells at their nearest position on *target_x*, NaN everywhere else.

    A scatter, not an interpolation: every stored value is one the model actually produced, moved
    by at most half a target cell to the nearest column of the finer grid. Nothing is invented for
    the cells in between, which stay NaN.

    Note that ``reindex(X=target_x, method='nearest')`` is *not* this. That fills every target cell
    from the nearest source cell, which is a piecewise-constant upsample -- it would present a
    10-cell result as though it resolved 3500 cells.

    Args:
        dataset: An xarray Dataset with an X coordinate of physical positions.
        target_x: The X coordinate to place it on.

    Returns:
        The dataset on *target_x*, or None if two of its cells would land on the same target cell,
        which would silently discard one of them.
    """
    source_x = np.asarray(dataset['X'].values, dtype=float)
    if len(source_x) == len(target_x) and np.allclose(source_x, target_x):
        return dataset

    nearest = np.abs(target_x[np.newaxis, :] - source_x[:, np.newaxis]).argmin(axis=1)
    snapped = target_x[nearest]
    if len(np.unique(snapped)) != len(snapped):
        return None

    return dataset.assign_coords(X=snapped).reindex(X=target_x)


def _align_stage_grids(datasets):
    """Put every stage's dataset for one category on a single X coordinate.

    The target is the grid with the most cells, so the finest stage -- the one a refinement chain
    exists to produce -- stays dense on its own grid. Aligning on the union of every stage's cell
    positions instead, which is what xr.concat does unaided, punches NaN holes into that stage at
    the coarse stages' positions.

    Falls back to the union if any stage cannot be snapped without collision, which is lossless
    where snapping would not be.

    Args:
        datasets: One dataset per stage, in stage order.

    Returns:
        tuple: (datasets to concatenate, index of the stage whose grid was used, or None if the
        union was kept).
    """
    grids = [np.asarray(ds['X'].values, dtype=float) for ds in datasets]
    first = grids[0]
    if all(grid.shape == first.shape and np.array_equal(grid, first) for grid in grids):
        return datasets, 0

    # Most cells wins, and a tie goes to the later stage: a chain that keeps nx and redistributes
    # the cells is refining part of the column, and the stage it refined *to* is the one to report
    # on. Comparing cell counts alone would call those two grids identical and leave the union.
    sizes = [len(grid) for grid in grids]
    finest = max(range(len(sizes)), key=lambda index: (sizes[index], index))
    target_x = grids[finest]

    aligned = [snap_to_grid(ds, target_x) for ds in datasets]
    if any(ds is None for ds in aligned):
        print('Warning: stage grids do not nest, so two cells of one stage would land on the same '
              'cell of the finest. Keeping the union of all stage positions instead, which loses '
              'nothing but leaves gaps in every stage.')
        return datasets, None

    return aligned, finest


def concat_staged_results(stages_dict):
    """Concatenate results from all stages along time, onto one grid.

    Where the stages share a grid this is a plain concatenation into the first stage, as it has
    always been. Where a chain changes resolution, each stage's cells are placed at their nearest
    position on the finest stage's grid and the cells no stage covers are left NaN, so the record
    of the coarse spin-up is kept at the depths it was computed for without inventing values
    between them.

    The results go to the stage whose grid they are on, so that anything deriving geometry from the
    returned InputFile -- core.attributes.initial_conditions, via omphalos.labels -- reads the same
    grid the results are on.

    Args:
        stages_dict: Dict mapping stage_num to InputFile for this run.

    Returns:
        int: The stage number the concatenated results were written to.
    """
    num_stages = len(stages_dict)

    produced = [(stage_num, stages_dict[stage_num].results) for stage_num in range(num_stages)
                if stages_dict[stage_num].results]

    if len(produced) <= 1:
        return produced[0][0] if produced else 0

    # The union across stages, not the first stage's alone: a category only a later stage produced
    # would otherwise be dropped. Sorted so the netCDF group order does not vary between runs.
    categories = sorted({category for _, results in produced for category in results})

    concatenated = {}
    host = 0
    for category in categories:
        stage_nums = [stage_num for stage_num, results in produced if category in results]
        datasets = [results[category] for _, results in produced if category in results]

        if len(datasets) == 1:
            concatenated[category] = datasets[0]
            continue

        aligned, finest = _align_stage_grids(datasets)
        concatenated[category] = xr.concat(aligned, dim='time')
        if finest is not None:
            host = max(host, stage_nums[finest])

    stages_dict[host].results = concatenated

    return host
