"""Module for generating multiple input files iteratively, to make large data sets for testing."""

# Global var defining the relationship between keyword blocks and YAML file entries.
# Takes the form {'yaml_entry_name': [CRUNCHTOPE_KEYWORD, var_array_pos]}
CT_IDs = {'runtime': ['RUNTIME', -1],
          'output': ['OUTPUT', slice(None)],
          'concentrations': ['geochemical condition', -1],
          'mineral_volumes': ['geochemical condition', 0],
          'mineral_ssa': ['geochemical condition', -1],
          'parameters': ['geochemical condition', -1],
          'gases': ['geochemical condition', -1],
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
    import subprocess

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
        subprocess.run(['cp', f'{template.config["database"]}', f'{tmp_dir}{template.config["database"]}'])
        # Check for a temperature file specification and copy it to tmp if there.
        try:
            if template.keyword_blocks['TEMPERATURE'].contents['read_temperaturefile']:
                subprocess.run(['cp', f'{template.keyword_blocks["TEMPERATURE"].contents["read_temperaturefile"][-1]}',
                                f'{tmp_dir}/{template.keyword_blocks["TEMPERATURE"].contents["read_temperaturefile"][-1]}'])
        except KeyError:
            pass

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
    import omphalos.parameter_methods as pm

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
    import subprocess
    import copy

    config = template.config
    num_files = config['number_of_files']
    num_stages = config['restart_chain']['stages']

    # Validate restart_chain keys
    valid_restart_chain_keys = {'stages', 'spatial_profile'}
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
            from omphalos.input_file import InputFile
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

            # Configure spatial_profile for staged output
            if 'spatial_profile' in config.get('restart_chain', {}):
                # Use explicitly specified spatial_profile from config
                _configure_spatial_profile(input_file, config['restart_chain']['spatial_profile'], stage_num)
            elif stage_num > 0 and 'spatial_profile' in input_file.keyword_blocks['OUTPUT'].contents:
                # Auto-adjust template's spatial_profile for stages > 0
                _auto_adjust_spatial_profile(input_file, stage_num)

            staged_file_dict[run_num][stage_num] = input_file

    if not rhea:
        subprocess.run(['cp', f'{template.config["database"]}', f'{tmp_dir}{template.config["database"]}'])
        try:
            if template.keyword_blocks['TEMPERATURE'].contents['read_temperaturefile']:
                subprocess.run(['cp', f'{template.keyword_blocks["TEMPERATURE"].contents["read_temperaturefile"][-1]}',
                                f'{tmp_dir}/{template.keyword_blocks["TEMPERATURE"].contents["read_temperaturefile"][-1]}'])
        except KeyError:
            pass

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
