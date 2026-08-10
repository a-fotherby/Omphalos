"""Methods to handle invoking CrunchTope on an InputFile object."""

import subprocess
import sys
from pathlib import Path

import numpy as np
import pexpect as pexp
import xarray as xr

from core import spatial_constructor as sc
from omphalos.settings import crunch_dir

# Error patterns searched in CrunchTope stdout. pexpect returns the index of the
# first match, so more specific strings should come before generic ones.
CT_ERROR_PATTERNS = [
    # Startup failure: CrunchTope truncates the input file path to a fixed-length buffer, so a
    # deeply nested working directory makes it lose the file and then block on stdin. Without this
    # pattern the run sits until the configured timeout with no indication of why.
    'Cannot find input file',
    'EXCEEDED MAXIMUM ITERATIONS',
    'TRY A',
    'divide by zero',
    'NaN',
    'forrtl:',            # Fortran runtime error prefix
    'Segmentation fault',
    'Killed',
    'FATAL',
]


def _get_kinetic_db_name(input_file):
    """Get the kinetic database filename from RUNTIME block.

    CrunchTope accepts both 'kinetic_database' and 'aqueousdatabase' keywords.

    Args:
        input_file: InputFile object with parsed keyword blocks.

    Returns:
        str: Kinetic database filename, or None if not found.
    """
    runtime_contents = input_file.keyword_blocks['RUNTIME'].contents
    if 'kinetic_database' in runtime_contents:
        return runtime_contents['kinetic_database'][0]
    elif 'aqueousdatabase' in runtime_contents:
        return runtime_contents['aqueousdatabase'][0]
    return None


def _print_aux_files(input_file, tmp_path):
    """Write auxiliary database and pathway files to the run directory."""
    if input_file.aqueous_database:
        kinetic_db = _get_kinetic_db_name(input_file)
        if kinetic_db:
            input_file.aqueous_database.print(str(tmp_path / kinetic_db))
    if input_file.catabolic_pathways:
        input_file.catabolic_pathways.print(str(tmp_path / 'CatabolicPathways.in'))


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


def crunchtope(input_file, file_num, timeout, tmp_dir, file_offset=0):
    """Execute CrunchTope on an input file.

    Args:
        input_file: InputFile object to run
        file_num: File number for logging
        timeout: Timeout in seconds
        tmp_dir: Working directory (Path object)
        file_offset: Offset for TecPlot file numbering (used in staged restarts).
    """
    command = f'{crunch_dir} {input_file.path}'
    process = pexp.spawn(command, timeout=timeout, cwd=str(tmp_dir), encoding='latin-1')
    process.logfile = sys.stdout

    expect_list = [pexp.EOF, pexp.TIMEOUT] + CT_ERROR_PATTERNS
    error_code = process.expect(expect_list)

    if error_code == 0:
        input_file.get_results(str(tmp_dir), file_offset=file_offset)
        print(f'File {file_num} outputs recorded.')
    elif error_code == 1:
        print(f'File {file_num} timed out.')
        input_file.error_code = error_code
    else:
        pattern = CT_ERROR_PATTERNS[error_code - 2]
        print(f'Error in file {file_num}: "{pattern}".')
        input_file.error_code = error_code

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

    if not rf.verify_identity(path, nx_in, dims):
        raise rf.RstError(
            f'{path.name} does not round-trip at nx={nx_in}, so its layout is not understood. '
            'Refusing to regrid: the result would be a plausible file with its fields misaligned.'
        )

    inject = {}
    porosity = _porosity_profile(current, nx_out)
    if porosity is not None:
        inject['por'] = porosity

    print(f'Regridding {path.name} from {nx_in} to {nx_out} cells for stage {stage_num}.')
    regridded = path.with_suffix(path.suffix + '.regrid.tmp')
    try:
        _, rewritten = rf.regrid(path, nx_in, nx_out, regridded, dims, inject=inject,
                                 deck=Path(current.path) if current.path else None,
                                 zones_in=zones_in, zones_out=zones_out)
        regridded.replace(path)
    finally:
        regridded.unlink(missing_ok=True)

    if rewritten:
        print(f'  re-derived for consistency: {", ".join(rewritten)}')
    if inject:
        print(f'  injected porosity from the stage {stage_num} deck')

    return True


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
    file_offset = 0

    for stage_num in range(num_stages):
        stage_file = stages_dict[stage_num]

        if stage_num == 0:
            _print_aux_files(stage_file, tmp_path)
        else:
            # A .rst carries no grid metadata, so a stage that changes xzones fails on its first
            # array read unless the file is resampled first.
            regrid_between_stages(stages_dict, stage_num, tmp_path)

        print(f'Running run {run_num}, stage {stage_num}')
        crunchtope(stage_file, run_num, timeout, tmp_path, file_offset=file_offset)

        if 'spatial_profile' in stage_file.keyword_blocks['OUTPUT'].contents:
            file_offset += len(stage_file.keyword_blocks['OUTPUT'].contents['spatial_profile'])

        if stage_file.error_code != 0:
            print(f'Error in run {run_num}, stage {stage_num}. Stopping staged execution.')
            break

    concat_staged_results(stages_dict)

    return stages_dict[0]


def concat_staged_results(stages_dict):
    """Concatenate results from all stages into the first stage InputFile.

    Args:
        stages_dict: Dict mapping stage_num to InputFile for this run.
    """
    num_stages = len(stages_dict)

    stage_results = []
    for stage_num in range(num_stages):
        stage_file = stages_dict[stage_num]
        if stage_file.results:
            stage_results.append(stage_file.results)

    if len(stage_results) <= 1:
        return

    first_stage = stages_dict[0]
    concatenated_results = {}

    for category in first_stage.results:
        datasets = []
        for stage_result in stage_results:
            if category in stage_result:
                datasets.append(stage_result[category])

        if len(datasets) > 1:
            concatenated_results[category] = xr.concat(datasets, dim='time')
        elif len(datasets) == 1:
            concatenated_results[category] = datasets[0]

    first_stage.results = concatenated_results
