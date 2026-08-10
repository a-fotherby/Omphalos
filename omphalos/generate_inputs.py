"""Module for generating multiple input files iteratively, to make large data sets for testing."""

import copy
import re
import shutil
from pathlib import Path

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
          'namelists': [None]
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
        name = (stage_grid or {}).get('porosity_file')
        if name and name not in found:
            found.append(name)

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

    # Validate restart_chain keys
    valid_restart_chain_keys = {'stages', 'spatial_profile', 'grid'}
    unknown_keys = set(config['restart_chain'].keys()) - valid_restart_chain_keys
    if unknown_keys:
        raise ValueError(
            f"Unknown key(s) in restart_chain: {unknown_keys}. "
            f"Valid keys are: {valid_restart_chain_keys}"
        )

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
                {}  # No later_inputs for staged runs - we handle stages differently
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
            _configure_restart_directives(input_file, run_num, stage_num, num_stages)

            # Apply this stage's grid, if the chain changes resolution between stages
            _configure_grid(input_file, config, stage_num)

            # Configure spatial_profile for staged output
            if 'spatial_profile' in config.get('restart_chain', {}):
                # Use explicitly specified spatial_profile from config
                _configure_spatial_profile(input_file, config['restart_chain']['spatial_profile'], stage_num)
            elif stage_num > 0 and 'spatial_profile' in input_file.keyword_blocks['OUTPUT'].contents:
                # Auto-adjust template's spatial_profile for stages > 0
                _auto_adjust_spatial_profile(input_file, stage_num)

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
        else:
            keyword_dict = modified_params[block]
            block_name = CT_IDs[block][0]
            mod_pos = CT_IDs[block][1]
            for entry in keyword_dict:
                change_list = keyword_dict[entry]
                input_file.keyword_blocks[block_name].modify(entry, change_list[run_num], mod_pos)


def _configure_restart_directives(input_file, run_num, stage_num, num_stages):
    """Configure restart and save_restart directives in the RUNTIME block.

    Args:
        input_file: The InputFile object to configure.
        run_num: The parallel run number.
        stage_num: The current stage index (0-indexed).
        num_stages: Total number of stages.
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

    # Set restart for all stages except the first
    if stage_num > 0:
        prev_restart_filename = f'restart_{run_num}_stage{stage_num - 1}.rst'
        runtime_block.contents['restart'] = [prev_restart_filename, 'append']
    else:
        # Remove restart for first stage if it exists
        if 'restart' in runtime_block.contents:
            del runtime_block.contents['restart']


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

    unknown = set(grid) - {'xzones', 'porosity_file'}
    if unknown:
        raise ValueError(
            f"ConfigError: Unknown key(s) in restart_chain grid for stage {stage_num}: {unknown}. "
            f"Valid keys are: {{'xzones', 'porosity_file'}}"
        )

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
        for existing in [k for k in porosity.contents if k.lower() == 'read_porosityfile']:
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

        porosity.contents['read_PorosityFile'] = [str(grid['porosity_file'])]


def _configure_spatial_profile(input_file, spatial_profile_config, stage_num):
    """Configure spatial_profile times in the OUTPUT block for staged restarts.

    For stages after the first, the times are offset by the cumulative time
    from all previous stages (using the last value of each stage's spatial_profile).

    Args:
        input_file: The InputFile object to configure.
        spatial_profile_config: List of lists, one per stage, containing the
            spatial_profile times for that stage.
        stage_num: The current stage index (0-indexed).
    """
    output_block = input_file.keyword_blocks['OUTPUT']

    # Get the times for this stage
    stage_times = spatial_profile_config[stage_num]

    # Calculate cumulative offset from previous stages
    offset = 0.0
    for prev_stage in range(stage_num):
        prev_times = spatial_profile_config[prev_stage]
        offset += prev_times[-1]  # Add the last time from each previous stage

    # Apply offset to times (no offset for stage 0)
    if stage_num > 0:
        adjusted_times = [t + offset for t in stage_times]
    else:
        adjusted_times = list(stage_times)

    # Convert to strings for the keyword block
    output_block.contents['spatial_profile'] = [str(t) for t in adjusted_times]


def _auto_adjust_spatial_profile(input_file, stage_num):
    """Automatically adjust spatial_profile times for stages > 0.

    When no explicit spatial_profile is specified in restart_chain, this function
    offsets the template's spatial_profile times based on the stage number.
    Each stage is assumed to have the same duration (the last time in the template's
    spatial_profile).

    Args:
        input_file: The InputFile object to configure.
        stage_num: The current stage index (0-indexed, must be > 0).
    """
    output_block = input_file.keyword_blocks['OUTPUT']

    # Get the original spatial_profile times from the template
    original_times = [float(t) for t in output_block.contents['spatial_profile']]

    # Use the last time as the stage duration
    stage_duration = original_times[-1]

    # Calculate offset: stage_num * stage_duration
    offset = stage_num * stage_duration

    # Offset all times (skip the first near-zero time to avoid conflict with restart)
    # Filter out times that would be at or before the restart time
    adjusted_times = [t + offset for t in original_times if t + offset > offset]

    # Convert to strings for the keyword block
    output_block.contents['spatial_profile'] = [str(t) for t in adjusted_times]
