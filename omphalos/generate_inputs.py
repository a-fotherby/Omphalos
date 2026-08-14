"""Module for generating multiple input files iteratively, to make large data sets for testing."""

import copy
import re
import shutil
from pathlib import Path

import numpy as np

import core.keyword_block as kb
import core.spatial_constructor as sc
import omphalos.parameter_methods as pm

from omphalos.input_file import InputFile

# CrunchTope reads several spatial fields from auxiliary files rather than from the deck:
# read_PorosityFile, read_saturationfile, read_temperaturefile, read_TortuosityFile, read_permfile,
# read_flowfile, read_velocityfile, read_burialfile and their relatives. Matching the shape of the
# keyword rather than listing them means a deck using one Omphalos has not seen before still gets
# its data staged alongside it.
AUX_FILE_KEYWORD = re.compile(r'^read_\w*file$', re.IGNORECASE)

# Global var defining the relationship between keyword blocks and YAML file entries.
# Takes the form {'yaml_entry_name': [CRUNCHTOPE_KEYWORD, var_array_pos]}
CT_IDs = {'runtime': ['RUNTIME', -1],
          'output': ['OUTPUT', slice(None)],
          'concentrations': ['geochemical condition', -1],
          'mineral_volumes': ['geochemical condition', 0],
          # mineral_ssa's position is found from the entry itself, since the surface area value sits at
          # a different offset depending on which of the manual's forms the condition uses.
          'mineral_ssa': ['geochemical condition', -1],
          'parameters': ['geochemical condition', -1],
          'gases': ['geochemical condition', -1],
          'exchangers': ['geochemical condition', -1],
          'surface_complexes': ['geochemical condition', -1],
          'mineral_rates': ['MINERALS', -1],
          'aqueous_kinetics': ['AQUEOUS_KINETICS', -1],
          'flow': ['FLOW', 0],
          'transport': ['TRANSPORT', -1],
          'erosion/burial': ['EROSION/BURIAL', -1],
          'boundary_conditions': ['BOUNDARY_CONDITIONS', 0],
          'namelists': [None],
          # 'database' is already the config key naming the .dbs path, so the sweepable parameters
          # inside it live under 'database_parameters'.
          'database_parameters': [None]
          }

CT_NMLs = {'aqueous': ['aqueous_database', 'Aqueous'],
           'aqueous_kinetics': ['aqueous_database', 'AqueousKinetics'],
           'catabolic_pathways': ['catabolic_pathways', 'CatabolicPathway']}


def auxiliary_files(input_file):
    """Return the auxiliary data files an input file's keyword blocks name.

    CrunchTope takes the filename as the *first* token of a ``read_*file`` keyword; a trailing token
    is a format specifier, as in ``read_PorosityFile porosity.dat FullForm`` (``StartTope.F90``
    passes the two to ``readFileName`` separately). Indexing the last token instead would try to
    copy a file called ``FullForm``.

    Args:
        input_file: An InputFile or Template whose keyword blocks have been read.

    Returns:
        list of filenames, in first-seen order and without duplicates.
    """
    found = []
    for block in (getattr(input_file, 'keyword_blocks', None) or {}).values():
        for keyword, entry in (getattr(block, 'contents', None) or {}).items():
            if not AUX_FILE_KEYWORD.match(keyword) or not entry:
                continue
            name = entry[0]
            if name and name not in found:
                found.append(name)

    return found


def config_auxiliary_files(config):
    """Return the auxiliary files a config names that no keyword block mentions yet.

    A ``restart_chain`` with per-stage grids names a porosity file for each stage. Only one of them
    can be in the template at a time, so discovery that reads the template alone would stage the
    wrong one -- or none.

    Args:
        config: The config yaml file, as a dict.

    Returns:
        list of filenames, in stage order and without duplicates.
    """
    found = []
    for stage_grid in (config.get('restart_chain') or {}).get('grid') or []:
        # The filename may carry a trailing format specifier, which is not part of the path.
        name = str((stage_grid or {}).get('porosity_file') or '').split(' ')[0]
        if name and name not in found:
            found.append(name)
        # Files a 'refine' shorthand generated. They exist by the time this is read, because
        # resolve_grid writes them as it resolves.
        for refined in ((stage_grid or {}).get('files') or {}).values():
            if refined not in found:
                found.append(refined)

    return found


def support_files(template, config=None):
    """Return every file a run needs beside its input deck, other than the databases.

    Collects the template's own auxiliary files, those of any later input files, and those a config
    names per stage.

    Absolutely-pathed files are left out: CrunchTope resolves those identically from any run
    directory, so there is nothing to stage.

    Args:
        template: The Template object the run is generated from.
        config: The config yaml file, as a dict. Optional; the template's own config is used if it
            has one and none is given.

    Returns:
        list of filenames relative to the working directory, without duplicates.
    """
    if config is None:
        config = getattr(template, 'config', None) or {}

    found = auxiliary_files(template)
    for later in (getattr(template, 'later_inputs', None) or {}).values():
        found.extend(auxiliary_files(later))
    found.extend(config_auxiliary_files(config))

    staged = []
    for name in found:
        if Path(name).is_absolute() or name in staged:
            continue
        staged.append(name)

    return staged


def stage_support_files(template, tmp_dir):
    """Copy the database and every auxiliary data file into the run directory.

    Only the database and the temperature file used to be copied, so a deck reading porosity,
    saturation, tortuosity or permeability from disk ran without them.

    A missing file is reported rather than raised on: CrunchTope will fail on it soon enough, and
    the message here says which file and why, where the one from CrunchTope does not.

    Args:
        template: The Template object the run is generated from.
        tmp_dir: Directory the input files are being written to.
    """
    destination = Path(tmp_dir)

    database = template.config.get('database')
    if database:
        shutil.copy(database, destination / Path(database).name)

    for name in support_files(template):
        # Keep the relative path rather than flattening to the basename: CrunchTope opens the name
        # exactly as the deck writes it, so 'data/porosity.dat' has to land in a 'data' subdirectory.
        target = destination / name
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(name, target)
        except OSError as error:
            print(f'Warning: could not stage auxiliary file "{name}" named by the input deck '
                  f'({error.strerror}). CrunchTope will not find it.')


def get_block_changes(block, num_files, stage_num=None):
    block_changes = {}
    for entry in block:
        change = block[entry]
        # Generate the list of values for all input files.
        change_list = get_config_array(change[0], change[1], num_files, stage_num=stage_num)
        block_changes.update({entry: change_list})

    return block_changes


def evaluate_config(config, stage_num=None):
    """Parse and evaluate the config file, returning a nested dictionary containing all the values needed to modify
    the InputFiles comprising the dataset.

    Args:
        config: The config yaml file, as a dict.
        stage_num: Optional stage index for staged parameter methods.
    """
    modified_params = {}
    num_files = config['number_of_files']

    # Blocks are dicts in the config.
    # Blocks are made up of changes.
    # Each change refers to a specific input file entry, and how to modify it.
    # Each change is a dict entry, with structure {entry_name: [instructions]}

    # Cycle through each known keyword block.
    # If the keyword block key is found in the config then proceed to modify the input files.
    for block in CT_IDs:
        # Check if we should run namelists code:
        if block == 'namelists' and block in config:
            modified_nmls = {}
            for nml_type in CT_NMLs:
                if nml_type in config['namelists']:
                    nml_block = config['namelists'][nml_type]
                    block_changes = {}
                    for reaction in nml_block:
                        reaction_block = nml_block[reaction]
                        block_changes.update({reaction: get_block_changes(reaction_block, num_files, stage_num=stage_num)})

                    modified_nmls.update({nml_type: block_changes})

            modified_params.update({'namelists': modified_nmls})

        elif block == 'database_parameters' and block in config:
            # Nested section -> entry -> parameter, so one level deeper than a keyword block.
            modified_database = {}
            for section in config[block]:
                section_block = config[block][section]
                entry_changes = {}
                for entry in section_block:
                    entry_changes.update(
                        {entry: get_block_changes(section_block[entry], num_files,
                                                  stage_num=stage_num)}
                    )

                modified_database.update({section: entry_changes})

            modified_params.update({block: modified_database})

        elif block in config:
            # Handle differently depending on whether this is a geochemical condition:
            # Extra layer of nesting to deal with naming for geochemical conditions.
            if CT_IDs[block][0] == 'geochemical condition':
                block_changes = {}
                for condition in config[block]:
                    condition_changes = get_block_changes(config[block][condition], num_files, stage_num=stage_num)
                    block_changes.update({condition: condition_changes})

            else:
                block_changes = get_block_changes(config[block], num_files, stage_num=stage_num)

            modified_params.update({block: block_changes})

    return modified_params


def configure_input_files(template, tmp_dir, rhea=False, override_num=-1):
    """Create a dictionary of InputFile objects that have randomised parameters in the range [var_min, var_max] for
    the specified condition. """
    if template.config['conditions'] is not None:
        for condition in template.config['conditions']:
            template.sort_condition_block(condition)

    file_dict = template.make_dict()

    if override_num != -1:
        # Do it to all files so that accidental call is obvious.
        for file in file_dict:
            file_dict[file].file_num = override_num

    modified_params = evaluate_config(template.config)

    if template.config['conditions'] is not None:
        for file in file_dict:
            for condition in template.config['conditions']:
                file_dict[file].sort_condition_block(condition)

    # For every entry in the modified_params dict update the input file.
    for block in modified_params:
        if CT_IDs[block][0] == 'geochemical condition':
            condition_dict = modified_params[block]
            mod_pos = CT_IDs[block][1]
            for condition in condition_dict:
                condition_block = condition_dict[condition]
                for entry in condition_block:
                    change_list = condition_block[entry]
                    for file in file_dict:
                        file_num = file_dict[file].file_num
                        file_dict[file].condition_blocks[condition].modify(entry, change_list[file_num], mod_pos,
                                                                           species_type=block)
        elif block == 'namelists':
            namelist_dict = modified_params['namelists']
            for nml_type in namelist_dict:
                nml_name = CT_NMLs[nml_type][0]
                list_name = CT_NMLs[nml_type][1]
                reactions = namelist_dict[nml_type]
                for reaction_name in reactions:
                    reaction = reactions[reaction_name]
                    for parameter in reaction:
                        change_list = reaction[parameter]
                        for file in file_dict:
                            file_num = file_dict[file].file_num
                            namelist = file_dict[file].__getattribute__(nml_name)
                            reaction_namelist = namelist.find_reaction(list_name, reaction_name)
                            reaction_namelist[parameter] = change_list[file_num]

        elif block == 'database_parameters':
            for file in file_dict:
                _apply_database_changes(file_dict[file], modified_params[block],
                                        file_dict[file].file_num)

        else:
            keyword_dict = modified_params[block]
            block_name = CT_IDs[block][0]
            mod_pos = CT_IDs[block][1]
            for entry in keyword_dict:
                change_list = keyword_dict[entry]
                for file in file_dict:
                    file_num = file_dict[file].file_num
                    file_dict[file].keyword_blocks[block_name].modify(entry, change_list[file_num], mod_pos)

    if not rhea:
        stage_support_files(template, tmp_dir)

    if template.later_inputs:
        for file in file_dict:
            for key in file_dict[file].later_inputs:
                later_file = \
                    configure_input_files(file_dict[file].later_inputs[key], tmp_dir, rhea, file_dict[file].file_num)[0]
                file_dict[file].later_inputs.update({key: later_file})

    return file_dict


def _apply_database_changes(input_file, database_dict, run_num):
    """Apply thermodynamic database edits to one InputFile.

    Args:
        input_file: The InputFile whose database is to be edited.
        database_dict: The 'database_parameters' entry of modified_params, nested
            section -> entry -> parameter -> list of values, one per run.
        run_num: The run number to index those lists with.

    Raises:
        ValueError: If the config sweeps database parameters without naming a database. Silently
            doing nothing would run every case against the same unedited file.
    """
    if input_file.database is None:
        raise ValueError(
            "ConfigError: 'database_parameters' needs a 'database' entry naming the .dbs file to "
            'edit.'
        )

    for section in database_dict:
        for entry in database_dict[section]:
            for parameter, change_list in database_dict[section][entry].items():
                input_file.database.modify(section, entry, parameter, change_list[run_num])


def get_config_array(spec, params, num_files, *, ref_vars=None, stage_num=None):
    """Extract a value to assign from the config file.

    Args:
        spec: The parameter method specification (e.g., 'linspace', 'staged').
        params: Parameters for the method.
        num_files: The number of files in the run.
        ref_vars: The rest of the keyword block, in case it needs to be referred to.
            This is for the fix_ratio case.
        stage_num: The stage index for staged parameter methods.
    """
    dispatch = {'linspace': pm.linspace,
                'random_uniform': pm.random_uniform,
                'constant': pm.constant,
                'custom': pm.custom_list,
                'fix_ratio': pm.fix_ratio,
                'staged': pm.staged
                }

    # Check to make sure the keyword is in the config_entry.
    # Look at first entry to determine behaviour.
    try:
        if spec == 'staged':
            array = dispatch[spec](params, num_files, stage_num=stage_num)
        else:
            array = dispatch[spec](params, num_files)
    except KeyError as e:
        raise ValueError(
            f'ConfigError: Unknown parameter setting "{spec}". '
            f'Valid options are: {list(dispatch.keys())}'
        ) from e

    return array


def has_staged_params(config):
    """Check if config contains any staged parameters.

    Args:
        config: The config yaml file, as a dict.

    Returns:
        bool: True if any parameters use the 'staged' method.
    """
    for block in CT_IDs:
        if block == 'namelists' and block in config:
            for nml_type in CT_NMLs:
                if nml_type in config['namelists']:
                    nml_block = config['namelists'][nml_type]
                    for reaction in nml_block:
                        reaction_block = nml_block[reaction]
                        for entry in reaction_block:
                            if reaction_block[entry][0] == 'staged':
                                return True
        elif block == 'database_parameters' and block in config:
            for section in config[block]:
                for entry in config[block][section]:
                    for parameter in config[block][section][entry]:
                        if config[block][section][entry][parameter][0] == 'staged':
                            return True
        elif block in config:
            if CT_IDs[block][0] == 'geochemical condition':
                for condition in config[block]:
                    for entry in config[block][condition]:
                        if config[block][condition][entry][0] == 'staged':
                            return True
            else:
                for entry in config[block]:
                    if config[block][entry][0] == 'staged':
                        return True
    return False


def configure_staged_input_files(template, tmp_dir, rhea=False):
    """Create a nested dictionary of InputFile objects for staged restart runs.

    Returns a dict of dicts: {run_num: {stage_num: InputFile}}

    Each run proceeds through stages sequentially, with restart files passed
    between stages.

    Args:
        template: The Template object containing config and input file data.
        tmp_dir: Temporary directory for running input files.
        rhea: Whether running under rhea (parallel execution).

    Returns:
        dict: Nested dictionary {run_num: {stage_num: InputFile}}
    """
    config = template.config
    num_files = config['number_of_files']
    num_stages = config['restart_chain']['stages']
    # A spinup restart starts the clock partway through, so every stage's output times
    # shift by it and the config's times stay durations.
    base_time = spinup_time(config)

    # Validate restart_chain keys
    valid_restart_chain_keys = {'stages', 'spatial_profile', 'grid'}
    unknown_keys = set(config['restart_chain'].keys()) - valid_restart_chain_keys
    if unknown_keys:
        raise ValueError(
            f"Unknown key(s) in restart_chain: {unknown_keys}. "
            f"Valid keys are: {valid_restart_chain_keys}"
        )

    # Expand any 'refine' shorthand into explicit grids and files before anything reads them. Done
    # once here rather than per run, since the grids do not vary between runs and the refined files
    # would otherwise be rewritten identically for every one of them.
    resolve_grid(config, template)

    if template.config['conditions'] is not None:
        for condition in template.config['conditions']:
            template.sort_condition_block(condition)

    # Create the nested dictionary structure
    staged_file_dict = {}

    for run_num in range(num_files):
        staged_file_dict[run_num] = {}

        for stage_num in range(num_stages):
            # Create a deep copy of the template for this run/stage
            input_file = copy.deepcopy(InputFile(
                template.config['template'],
                template.keyword_blocks,
                template.condition_blocks,
                template.aqueous_database,
                template.catabolic_pathways,
                {},  # No later_inputs for staged runs - we handle stages differently
                template.database
            ))
            input_file.file_num = run_num
            input_file.stage_num = stage_num

            # Sort condition blocks if needed
            if template.config['conditions'] is not None:
                for condition in template.config['conditions']:
                    input_file.sort_condition_block(condition)

            # Evaluate config with stage_num for staged parameters
            modified_params = evaluate_config(config, stage_num=stage_num)

            # Apply modifications
            _apply_modifications(input_file, modified_params, run_num)

            # Set up restart directives in RUNTIME block
            _configure_restart_directives(input_file, run_num, stage_num, num_stages,
                                          spinup_restart=config.get('restart_file'))

            # Apply this stage's grid, if the chain changes resolution between stages
            _configure_grid(input_file, config, stage_num)

            # A stage that changes grid reads a resampled copy of the previous stage's restart,
            # not the file itself. Done after _configure_grid, which is what sets this stage's
            # xzones and so decides whether a resample happens at all.
            if stage_num > 0:
                _name_regridded_restart(input_file, staged_file_dict[run_num][stage_num - 1])

            # Configure spatial_profile for staged output. Stage times stay durations even when
            # a spinup restart starts the clock partway through, which base_time carries.
            if 'spatial_profile' in config.get('restart_chain', {}):
                # Use explicitly specified spatial_profile from config
                _configure_spatial_profile(input_file, config['restart_chain']['spatial_profile'],
                                           stage_num, base_time=base_time)
            elif ((stage_num > 0 or base_time)
                    and any(key in input_file.keyword_blocks['OUTPUT'].contents
                            for key in kb.SNAPSHOT_TIME_KEYWORDS)):
                # Stage 0 needs adjusting too when a spinup moves the clock forward, or its
                # template times would land before the restart and CrunchTope would stop.
                _auto_adjust_spatial_profile(input_file, stage_num, base_time=base_time)

            staged_file_dict[run_num][stage_num] = input_file

    if not rhea:
        stage_support_files(template, tmp_dir)

    return staged_file_dict


def _apply_modifications(input_file, modified_params, run_num):
    """Apply parameter modifications to an InputFile.

    Args:
        input_file: The InputFile object to modify.
        modified_params: Dictionary of parameter modifications from evaluate_config.
        run_num: The run number (file_num) to use for indexing into change arrays.
    """
    for block in modified_params:
        if CT_IDs[block][0] == 'geochemical condition':
            condition_dict = modified_params[block]
            mod_pos = CT_IDs[block][1]
            for condition in condition_dict:
                condition_block = condition_dict[condition]
                for entry in condition_block:
                    change_list = condition_block[entry]
                    input_file.condition_blocks[condition].modify(
                        entry, change_list[run_num], mod_pos, species_type=block
                    )
        elif block == 'namelists':
            namelist_dict = modified_params['namelists']
            for nml_type in namelist_dict:
                nml_name = CT_NMLs[nml_type][0]
                list_name = CT_NMLs[nml_type][1]
                reactions = namelist_dict[nml_type]
                for reaction_name in reactions:
                    reaction = reactions[reaction_name]
                    for parameter in reaction:
                        change_list = reaction[parameter]
                        namelist = input_file.__getattribute__(nml_name)
                        reaction_namelist = namelist.find_reaction(list_name, reaction_name)
                        reaction_namelist[parameter] = change_list[run_num]
        elif block == 'database_parameters':
            _apply_database_changes(input_file, modified_params[block], run_num)
        else:
            keyword_dict = modified_params[block]
            block_name = CT_IDs[block][0]
            mod_pos = CT_IDs[block][1]
            for entry in keyword_dict:
                change_list = keyword_dict[entry]
                input_file.keyword_blocks[block_name].modify(entry, change_list[run_num], mod_pos)


def _configure_restart_directives(input_file, run_num, stage_num, num_stages,
                                  spinup_restart=None):
    """Configure restart and save_restart directives in the RUNTIME block.

    Stage 0 starts cold unless the config names a ``restart_file``. That file is copied into
    every run directory by ``rhea/prep_directories.sh``, but nothing referenced it: stage 0's
    ``restart`` keyword was deleted unconditionally, so a staged spinup was ignored and the
    chain silently recomputed it.

    Args:
        input_file: The InputFile object to configure.
        run_num: The parallel run number.
        stage_num: The current stage index (0-indexed).
        num_stages: Total number of stages.
        spinup_restart: The config's ``restart_file``, if any. Used as stage 0's starting
            state. Its output times are absolute, so the chain's stage 0 times must be later
            than the time stored in it -- CrunchTope stops with 'You have specified an output
            time < the restart time' otherwise.
    """
    runtime_block = input_file.keyword_blocks['RUNTIME']

    # Set save_restart for all stages except the last
    if stage_num < num_stages - 1:
        restart_filename = f'restart_{run_num}_stage{stage_num}.rst'
        runtime_block.contents['save_restart'] = [restart_filename]
    else:
        # Remove save_restart for last stage if it exists
        if 'save_restart' in runtime_block.contents:
            del runtime_block.contents['save_restart']

    # Later stages restart from the one before; stage 0 from the config's spinup, if given.
    if stage_num > 0:
        prev_restart_filename = f'restart_{run_num}_stage{stage_num - 1}.rst'
        runtime_block.contents['restart'] = [prev_restart_filename, 'append']
    elif spinup_restart:
        # 'append' is required, not cosmetic: without it prtint is left nstop long while nint
        # points past its end, so CrunchTope reads out of bounds and stops after one output.
        runtime_block.contents['restart'] = [spinup_restart, 'append']
    elif 'restart' in runtime_block.contents:
        del runtime_block.contents['restart']


def _stage_xzones(input_file):
    """The xzones tokens a stage's deck declares, or None if it declares none."""
    discretization = input_file.keyword_blocks.get('DISCRETIZATION')

    return discretization.contents.get('xzones') if discretization is not None else None


def _name_regridded_restart(input_file, previous_file):
    """Point a stage that changes grid at a resampled copy, not the previous stage's own restart.

    ``run.regrid_between_stages`` resamples the previous stage's restart onto this stage's grid.
    Writing that back over the source would leave ``restart_N_stageM.rst`` holding a file at the
    *next* stage's resolution -- a name that lies about its own grid. A ``.rst`` carries no grid
    metadata, and a Fortran unformatted read fills a short array from a long record without
    complaint, so anything later reusing that name by its face value gets a silently wrong initial
    state rather than an error. Naming the resampled copy after the cell count it actually holds
    removes the hazard, and leaves the coarse file intact and reusable as a spinup.

    Does nothing when the two stages share a grid: no resample happens, so this stage reads the
    previous stage's file exactly as it was written.

    Args:
        input_file: The stage being configured, with its grid already applied.
        previous_file: The stage before it, whose restart this one reads.
    """
    runtime_block = input_file.keyword_blocks.get('RUNTIME')
    restart = (getattr(runtime_block, 'contents', None) or {}).get('restart')
    if not restart:
        return

    zones_in, zones_out = _stage_xzones(previous_file), _stage_xzones(input_file)
    if zones_in is None or zones_out is None or zones_in == zones_out:
        return

    source = Path(restart[0])
    resampled = f'{source.stem}_nx{sc.zone_cell_count(zones_out)}{source.suffix}'
    runtime_block.contents['restart'] = [resampled, *restart[1:]]


#: Keys a user may write in a restart_chain grid entry. 'files' is added by resolve_grid.
VALID_GRID_KEYS = {'xzones', 'porosity_file', 'refine'}


def resolve_grid(config, template):
    """Expand the ``refine`` shorthand into explicit per-stage grids, in place.

    ``refine: 10`` on a stage means: take the previous stage's grid, split every cell into ten, and
    regenerate every spatial input file the deck reads to match. Written out by hand that is an
    xzones line and one file per ``read_*file`` keyword, per stage.

    ``refine`` may instead be a mapping, to choose how those files are resampled::

        refine: {factor: 10, method: linear}

    ``method`` is one of :data:`REFINE_METHODS` and defaults to ``step``. See
    :func:`refine_data_file` for which to pick: ``step`` cannot invent structure, but on a
    field whose steps are a binning artefact -- a layered ``read_PorosityFile`` is the usual
    case -- it hands the fine grid a discontinuity in the diffusion coefficient to resolve.

    The whole ``grid`` may be given as ``{'refine': 10}`` instead of a list, which applies the same
    factor at every stage after the first. That form also takes the mapping.

    Everything downstream sees explicit ``xzones`` and filenames, so nothing else needs to know the
    shorthand exists -- including the auxiliary-file staging, which picks up the generated files
    because they are named in the resolved config.

    Args:
        config: The config yaml file, as a dict. Its restart_chain grid is replaced in place.
        template: The Template, read for the starting grid and the files the deck names.

    Returns:
        list: The resolved grid, one entry per stage.
    """
    chain = config.get('restart_chain') or {}
    grid = chain.get('grid')
    if not grid:
        return []

    num_stages = chain.get('stages', 0)
    if isinstance(grid, dict):
        # A bare {'refine': N}: the first stage keeps the template's grid, the rest refine.
        grid = [{}] + [dict(grid) for _ in range(max(0, num_stages - 1))]

    for stage_num, entry in enumerate(grid):
        unknown = set(entry or {}) - VALID_GRID_KEYS
        if unknown:
            raise ValueError(
                f"ConfigError: Unknown key(s) in restart_chain grid for stage {stage_num}: "
                f"{unknown}. Valid keys are: {sorted(VALID_GRID_KEYS)}"
            )

    discretization = template.keyword_blocks.get('DISCRETIZATION')
    zones = list(discretization.contents.get('xzones', [])) if discretization else []
    # Filenames as the deck currently names them, updated stage by stage as they are refined.
    current_files = {name: name for name in auxiliary_files(template)}

    resolved = []
    for stage_num, entry in enumerate(grid):
        entry = dict(entry or {})
        factor, method = _refine_spec(entry.pop('refine', None), stage_num)

        if factor is not None:
            if not zones:
                raise ValueError(
                    f'ConfigError: restart_chain grid stage {stage_num} asks to refine, but '
                    'neither the template nor an earlier stage declares xzones to refine from.'
                )
            zones = refine_zones(zones, factor)
            entry['xzones'] = zones
            entry['files'] = _refine_stage_files(current_files, zones, factor, stage_num,
                                                 method=method)
            current_files = {original: entry['files'].get(current, current)
                             for original, current in current_files.items()}
        elif 'xzones' in entry:
            zones = [str(token) for token in entry['xzones']]

        resolved.append(entry)

    chain['grid'] = resolved

    return resolved


def _refine_spec(refine, stage_num):
    """Normalise a ``refine`` entry to ``(factor, method)``.

    Accepts the bare ``refine: 10`` shorthand and the explicit
    ``refine: {factor: 10, method: linear}`` form. Absent, returns ``(None, 'step')``.
    """
    if refine is None:
        return None, 'step'

    if isinstance(refine, dict):
        unknown = set(refine) - {'factor', 'method'}
        if unknown:
            raise ValueError(
                f'ConfigError: Unknown key(s) in restart_chain grid refine for stage '
                f"{stage_num}: {unknown}. Valid keys are: ['factor', 'method']"
            )
        if 'factor' not in refine:
            raise ValueError(
                f'ConfigError: restart_chain grid stage {stage_num} gives refine as a '
                "mapping but omits 'factor'."
            )
        factor, method = refine['factor'], refine.get('method', 'step')
    else:
        factor, method = refine, 'step'

    if method not in REFINE_METHODS:
        raise ValueError(
            f'ConfigError: unknown refine method {method!r} for stage {stage_num}. '
            f'Valid methods are: {sorted(REFINE_METHODS)}'
        )

    return factor, method


def _refine_stage_files(current_files, zones, factor, stage_num, method='step'):
    """Write a refined copy of each spatial input file, returning {old name: new name}.

    A file whose row count does not match the grid it is being refined from is left alone and
    reported. That covers the fields stored on cell faces rather than cell centres, whose row count
    convention differs, and a file that was already the wrong length before any of this.
    """
    nx_new = sc.zone_cell_count(zones)
    nx_old = nx_new // int(factor)
    renamed = {}

    for name in current_files.values():
        path = Path(name)
        try:
            rows = len(np.atleast_1d(np.loadtxt(path)))
        except OSError as error:
            print(f'Warning: cannot refine "{name}" for stage {stage_num} ({error.strerror}). '
                  'The stage will read it at its current length and CrunchTope will stop.')
            continue

        if rows != nx_old:
            print(f'Warning: "{name}" has {rows} rows, not the {nx_old} cells of the grid it is '
                  f'being refined from, so it has been left alone. Provide a stage {stage_num} '
                  'version by hand if CrunchTope needs one.')
            continue

        refined = path.with_name(f'{path.stem}_stage{stage_num}{path.suffix}')
        refine_data_file(path, refined, factor, zones, method=method)
        renamed[name] = str(refined)
        print(f'Refined {name} -> {refined} ({rows} -> {nx_new} rows, {method}) '
              f'for stage {stage_num}.')

    return renamed


def stage_grid(config, stage_num):
    """Return the grid settings a restart chain declares for one stage, or an empty dict.

    Args:
        config: The config yaml file, as a dict.
        stage_num: The stage index (0-indexed).

    Returns:
        dict of grid settings, empty if the chain declares no grid for this stage.
    """
    grids = (config.get('restart_chain') or {}).get('grid') or []
    if stage_num >= len(grids):
        return {}

    return grids[stage_num] or {}


def refine_zones(zones, factor):
    """Split every cell of an xzones specification into *factor* cells of equal width.

    Grading and total column length are both preserved exactly: a zone of 20 cells 5 cm wide
    becomes 20 * factor cells of 5 / factor cm.

    Args:
        zones: The tokens following an xzones keyword.
        factor: Integer refinement factor, at least 2.

    Returns:
        list of tokens for the refined grid.
    """
    if int(factor) != factor or factor < 2:
        raise ValueError(f'ConfigError: refine must be an integer of at least 2, got {factor!r}')

    factor = int(factor)
    refined = []
    for index in range(0, len(zones), 2):
        count = int(float(zones[index]))
        width = float(zones[index + 1]) if index + 1 < len(zones) else 1.0
        refined.extend([str(count * factor), f'{width / factor:.10g}'])

    return refined


def _cell_centres(zones, nx):
    """Physical cell-centre positions of a grid, measured from the start of the column."""
    from omphalos.restart_file import cell_widths

    edges = np.concatenate(([0.0], np.cumsum(cell_widths(zones, nx))))

    return 0.5 * (edges[:-1] + edges[1:])


#: How ``refine`` may resample a spatial input file onto the finer grid.
REFINE_METHODS = ('step', 'linear', 'smoothstep')


def _refine_values(values, factor, zones=None, method='step'):
    """Resample *factor*-fold refined cell values by *method*.

    ``step`` gives each fine cell the value of the coarse cell containing it. The others
    interpolate between coarse **cell centres**, so a change between two coarse cells is
    spread over the ``factor`` fine cells that span them; ``smoothstep`` uses the cubic
    ``3t^2 - 2t^3`` in place of the linear weight, leaving no slope discontinuity at either
    end of the ramp.

    Interpolating by position rather than by index matters on a graded grid. Because
    :func:`refine_zones` splits every coarse cell into *factor* equal parts, each coarse
    centre is the mean of its fine centres, which recovers the coarse positions exactly
    whatever the grading.
    """
    factor = int(factor)
    if method not in REFINE_METHODS:
        raise ValueError(
            f'ConfigError: unknown refine method {method!r}. '
            f'Valid methods are: {sorted(REFINE_METHODS)}'
        )
    if method == 'step':
        return np.repeat(values, factor)

    nx_new = len(values) * factor
    fine = _cell_centres(zones, nx_new) if zones else (np.arange(nx_new) + 0.5) / nx_new
    coarse = np.asarray(fine).reshape(len(values), factor).mean(axis=1)

    if method == 'linear':
        return np.interp(fine, coarse, values)

    # smoothstep: locate each fine centre in its bracketing coarse interval, then reweight.
    idx = np.clip(np.searchsorted(coarse, fine, side='right') - 1, 0, len(coarse) - 2)
    span = coarse[idx + 1] - coarse[idx]
    t = np.clip((fine - coarse[idx]) / np.where(span > 0, span, 1.0), 0.0, 1.0)

    return values[idx] + t * t * (3.0 - 2.0 * t) * (values[idx + 1] - values[idx])


def refine_data_file(source, destination, factor, zones=None, method='step'):
    """Write a refined copy of a spatial input file, *factor* fine cells per coarse cell.

    ``method='step'`` (the default) replicates each value, giving each fine cell the value of
    the coarse cell containing it. That is the same field sampled more finely and introduces
    nothing that was not already there, which is the right choice when the steps are real --
    a lithological contact, say.

    It is the wrong choice when the steps are an artefact of how the field was binned, and a
    ``read_PorosityFile`` usually is. Porosity enters transport as
    ``phi**cementation_exponent``, so a step the coarse grid was too blunt to resolve becomes
    a discontinuity in the diffusion coefficient that the fine grid resolves faithfully --
    as a staircase in the results. Ramping each step across the cells spanning it instead cuts
    the worst adjacent-cell porosity contrast by roughly the refinement factor, and more again
    in the ``phi**cementation_exponent`` transport sees, without moving peak rates or depths.
    Which method is right therefore depends on the field, not on the code, and ``step`` stays
    the default only because it cannot invent structure.

    A two-column file carries position alongside the value. CrunchTope reads that column into
    a dummy and discards it -- values go to cells 1..nx in file order -- but it is rewritten
    with the refined grid's cell centres so the file still reads correctly to a human.

    Args:
        source: File to refine.
        destination: File to write.
        factor: Integer refinement factor.
        zones: The refined grid's xzones tokens, used to place cell centres and to
            regenerate a position column. Omitting them assumes a uniform grid.
        method: One of :data:`REFINE_METHODS`.

    Returns:
        int: The number of rows written.
    """
    table = np.loadtxt(source)
    column = table if table.ndim == 1 else table[:, -1]
    values = _refine_values(np.atleast_1d(column), factor, zones, method)

    if table.ndim == 1:
        np.savetxt(destination, values)
    else:
        positions = (_cell_centres(zones, len(values)) if zones
                     else np.repeat(table[:, 0], int(factor)))
        np.savetxt(destination, np.column_stack([positions, values]))

    return len(values)


def rescale_region(bounds, nx_old, nx_new):
    """Map a 1-indexed inclusive cell range from one grid resolution to another.

    Zone edges are mapped through a single monotone boundary function, so abutting zones stay
    abutting: there is no gap or overlap where one ends and the next begins.

    Args:
        bounds: ``[first, last]`` cell numbers on the old grid, 1-indexed and inclusive.
        nx_old: Cell count the bounds are expressed on.
        nx_new: Cell count to express them on.

    Returns:
        list: ``[first, last]`` on the new grid.
    """
    def edge(cells):
        return int(cells * nx_new / nx_old + 0.5)

    first, last = edge(bounds[0] - 1) + 1, edge(bounds[1])

    # A zone thinner than one cell of the coarser grid would otherwise invert. Keeping one cell
    # overlaps the next zone, and the condition declared last wins, as it does everywhere else.
    return [first, max(first, last)]


def _rescale_initial_conditions(input_file, nx_old, nx_new):
    """Re-express the INITIAL_CONDITIONS regions on a new grid.

    CrunchTope aborts with 'You have specified a corner at JX > NX' if a region runs past the end of
    the grid, and silently leaves cells uninitialised if the regions stop short, so a stage that
    changes xzones has to move its regions with it.

    For stages after the first the initial condition is overwritten by the restart anyway, but
    CrunchTope still validates the regions at startup, and this keeps a stage runnable on its own.
    """
    block = input_file.keyword_blocks.get('INITIAL_CONDITIONS')
    if block is None or nx_old == nx_new:
        return

    rescaled = {}
    for coord_string, entry in block.contents.items():
        # The block title is stored under an empty key, with no coordinates to rescale.
        if not coord_string:
            rescaled[coord_string] = entry
            continue

        pairs = coord_string.split()
        bounds = [list(map(int, re.findall(r'\d+', pair))) for pair in pairs]
        if not bounds or len(bounds[0]) != 2:
            rescaled[coord_string] = entry
            continue

        bounds[0] = rescale_region(bounds[0], nx_old, nx_new)
        rescaled[' '.join(f'{lo}-{hi}' for lo, hi in bounds)] = entry

    block.contents = rescaled
    # region attributes are derived from the block, so they have to be re-read from it.
    input_file.condition_regions()


def _rename_data_file(input_file, original, refined):
    """Point every read_*file keyword naming *original* at *refined* instead.

    Only the filename token changes. Anything after it is a format specifier -- 'FullForm',
    'SingleColumn' -- and dropping it would leave CrunchTope reading the file under a different
    convention than the deck asked for.
    """
    for block in input_file.keyword_blocks.values():
        for keyword, entry in block.contents.items():
            if AUX_FILE_KEYWORD.match(keyword) and entry and entry[0] == original:
                block.contents[keyword] = [refined] + list(entry[1:])


def _warn_about_fixed_coordinates(input_file, stage_num):
    """Report deck entries that name a cell index the grid change does not move.

    INITIAL_CONDITIONS regions are rescaled, but a pump in the FLOW block carries its coordinates in
    the entry key and refers to a specific cell. Silently leaving it pointing somewhere else on the
    new grid would be the worst kind of wrong, so say so and let the operator decide.
    """
    flow = input_file.keyword_blocks.get('FLOW')
    pumps = [entry for entry in (flow.contents if flow else {}) if 'pump' in entry]
    if pumps:
        print(f'Warning: stage {stage_num} changes the grid, but the FLOW block pumps '
              f'{[entry.split("&")[0] for entry in pumps]} name fixed coordinates that have not '
              'been rescaled. Check they still point where you intend.')


def _configure_grid(input_file, config, stage_num):
    """Apply a restart chain's per-stage grid settings to one stage's input file.

    Absent a ``grid`` entry this does nothing, so a chain that does not change resolution behaves
    exactly as it did before.

    The porosity file is written into the deck here, but that alone is not enough: ``CALL restart``
    runs after ``CALL StartTope``, so a porosity resampled from the previous stage overrides
    whatever ``read_PorosityFile`` read. ``run.run_staged_input`` therefore also injects it into the
    regridded restart file.

    Args:
        input_file: The InputFile object to configure.
        config: The config yaml file, as a dict.
        stage_num: The current stage index (0-indexed).
    """
    grid = stage_grid(config, stage_num)
    if not grid:
        return

    for original, refined in (grid.get('files') or {}).items():
        _rename_data_file(input_file, original, refined)

    if 'xzones' in grid:
        discretization = input_file.keyword_blocks.setdefault(
            'DISCRETIZATION', kb.KeywordBlock('DISCRETIZATION'))
        discretization.contents.setdefault('DISCRETIZATION', [])

        previous = discretization.contents.get('xzones')
        nx_old = sc.zone_cell_count(previous) if previous else None
        discretization.contents['xzones'] = [str(token) for token in grid['xzones']]
        nx_new = sc.zone_cell_count(discretization.contents['xzones'])

        if nx_old:
            _rescale_initial_conditions(input_file, nx_old, nx_new)
            _warn_about_fixed_coordinates(input_file, stage_num)

    if 'porosity_file' in grid:
        porosity = input_file.keyword_blocks.setdefault('POROSITY', kb.KeywordBlock('POROSITY'))
        # The block's own name keys an empty entry, which is how print() writes the header line.
        porosity.contents.setdefault('POROSITY', [])
        # Written under the manual's spelling, but replacing whatever spelling the template used:
        # CrunchTope matches the keyword case insensitively, so leaving both in would read the
        # template's file rather than this stage's.
        format_tokens = []
        for existing in [k for k in porosity.contents if k.lower() == 'read_porosityfile']:
            format_tokens = list(porosity.contents[existing][1:])
            del porosity.contents[existing]

        # fix_porosity is read first and, if positive, jumps straight past read_porosityfile
        # (StartTope.F90:2938-2950 does GO TO 5011), so leaving it in place would silently discard
        # the file this stage is meant to read.
        superseded = [k for k in porosity.contents if k.lower() in ('fix_porosity', 'set_porosity')]
        for keyword in superseded:
            del porosity.contents[keyword]
        if superseded:
            print(f'Stage {stage_num} reads porosity from {grid["porosity_file"]}, so '
                  f'{superseded} has been dropped from its POROSITY block: CrunchTope would '
                  'otherwise ignore the file.')

        # Keep whatever format specifier followed the template's filename: dropping it would leave
        # CrunchTope reading a two-column FullForm file as a single column, or the reverse.
        tokens = str(grid['porosity_file']).split()
        if len(tokens) == 1 and format_tokens:
            tokens += format_tokens
        porosity.contents['read_PorosityFile'] = tokens


def spinup_time(config):
    """The simulated time a config's ``restart_file`` is stored at, or 0.0 if there is none.

    A chain's stage times are durations, accumulated stage by stage. A spinup restart breaks
    that: ``restart.F90`` restores the stored clock, so stage 0 begins at that time and an
    output time earlier than it makes CrunchTope stop with 'You have specified an output time
    < the restart time'. Adding this to every stage keeps the config's times durations rather
    than making the first stage's absolute.

    The stored time is in the run's internal time units, so this assumes the ``OUTPUT`` block
    uses the same units as ``RUNTIME`` -- true unless a deck deliberately mixes them.

    Args:
        config: The config yaml file, as a dict.

    Returns:
        float: The time to add to every stage's output times.
    """
    name = config.get('restart_file')
    if not name:
        return 0.0

    # The entry may carry a trailing 'append', which is not part of the path.
    path = Path(str(name).split(' ')[0])
    if not path.is_file():
        print(f'Warning: restart_file "{path}" was not found while setting stage output times, '
              'so they are treated as starting from time zero. If the file exists at run time '
              'and holds a later clock, CrunchTope will stop on the first output time.')
        return 0.0

    from omphalos.restart_file import RstError, stored_counters

    try:
        return float(stored_counters(path)['time'])
    except (RstError, OSError) as error:
        print(f'Warning: could not read the clock from restart_file "{path}" ({error}), so '
              'stage output times are treated as starting from time zero.')
        return 0.0


def _configure_spatial_profile(input_file, spatial_profile_config, stage_num, base_time=0.0):
    """Configure spatial_profile times in the OUTPUT block for staged restarts.

    Every stage's times are durations. They are offset by the cumulative duration of all
    previous stages (the last value of each), and by *base_time* -- the clock a spinup
    restart starts stage 0 at. Without that second term a chain given a spinup would have to
    write stage 0's times as absolute and the rest as durations.

    Args:
        input_file: The InputFile object to configure.
        spatial_profile_config: List of lists, one per stage, containing the
            spatial_profile times for that stage.
        stage_num: The current stage index (0-indexed).
        base_time: Simulated time the chain starts from, from :func:`spinup_time`.
    """
    output_block = input_file.keyword_blocks['OUTPUT']

    # Get the times for this stage
    stage_times = spatial_profile_config[stage_num]

    # Cumulative duration of the stages before this one, plus any spinup clock.
    offset = float(base_time)
    for prev_stage in range(stage_num):
        prev_times = spatial_profile_config[prev_stage]
        offset += prev_times[-1]  # Add the last time from each previous stage

    adjusted_times = [t + offset for t in stage_times]

    # Convert to strings for the keyword block
    # Written back under the spelling the deck already uses, so a template saying
    # 'spatial_profile_at_time' does not end up with both keywords.
    output_block.contents[kb.snapshot_key(output_block.contents)] = [str(t) for t in adjusted_times]


def _auto_adjust_spatial_profile(input_file, stage_num, base_time=0.0):
    """Automatically adjust spatial_profile times for stages > 0.

    When no explicit spatial_profile is specified in restart_chain, this function
    offsets the template's spatial_profile times based on the stage number.
    Each stage is assumed to have the same duration (the last time in the template's
    spatial_profile).

    Args:
        input_file: The InputFile object to configure.
        stage_num: The current stage index (0-indexed, must be > 0).
        base_time: Simulated time the chain starts from, from :func:`spinup_time`. Added to
            every stage so that a spinup does not have to be absorbed into the template.
    """
    output_block = input_file.keyword_blocks['OUTPUT']

    # Get the original snapshot times from the template, under either spelling
    original_times = [float(t) for t in kb.snapshot_times(output_block.contents)]

    # Use the last time as the stage duration
    stage_duration = original_times[-1]

    # Calculate offset: stage_num * stage_duration, plus any spinup clock.
    offset = stage_num * stage_duration + float(base_time)

    # Drop times that would land at or before the point this stage starts from, which
    # CrunchTope rejects: 'You have specified an output time < the restart time'.
    adjusted_times = [t + offset for t in original_times if t > 0]

    # Convert to strings for the keyword block, keeping the deck's own spelling.
    output_block.contents[kb.snapshot_key(output_block.contents)] = [str(t) for t in adjusted_times]
