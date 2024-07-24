"""Module for generating multiple input files iteratively, to make large data sets for testing."""

# Global var defining the relationship between keyword blocks and YAML file entries.
# Takes the form {'yaml_entry_name': [CRUNCHTOPE_KEYWORD, var_array_pos]}
CT_IDs = {'concentrations': ['geochemical condition', 0],
          'mineral_volumes': ['geochemical condition', 0],
          'mineral_ssa': ['geochemical condition', 1],
          'parameters': ['geochemical condition', 0],
          'gases': ['geochemical condition', -1],
          'time': ['time', 0],
          }

def get_block_changes(block, num_files):
    block_changes = {}
    for entry in block:
        change = block[entry]
        # Generate the list of values for all input files.
        change_list = get_config_array(change[0], change[1], num_files)
        block_changes.update({entry: change_list})

    return block_changes


def evaluate_config(config):
    """Parse and evaluate the config file, returning a nested dictionary containing all the values needed to modify
    the InputFiles comprising the dataset. """
    modified_params = {}
    num_files = config['number_of_files']

    # Blocks are dicts in the config.
    # Blocks are made up of changes.
    # Each change refers to a specific input file entry, and how to modify it.
    # Each change is a dict entry, with structure {entry_name: [instructions]}

    # Cycle through each known keyword block.
    # If the keyword block key is found in the config then proceed to modify the input files.
    for block in CT_IDs:
        if block in config:
            # Handle differently depending on whether this is a geochemical condition:
            # Extra layer of nesting to deal with naming for geochemical conditions.
            if CT_IDs[block][0] == 'geochemical condition':
                block_changes = {}
                for condition in config[block]:
                    condition_changes = get_block_changes(config[block][condition], num_files)
                    block_changes.update({condition: condition_changes})

            else:
                block_changes = get_block_changes(config[block], num_files)

            modified_params.update({block: block_changes})

    return modified_params


def configure_input_files(template, tmp_dir, rhea=False, override_num=-1):
    """Create a dictionary of InputFile objects that have randomised parameters in the range [var_min, var_max] for
    the specified condition. """
    import subprocess

    if template.restart == True:
        file_dict = {0: template}
    else:
        file_dict = template.make_dict()

    if override_num != -1:
        # Do it to all files so that accidental call is obvious.
        for file in file_dict:
            file_dict[file].file_num = override_num

    modified_params = evaluate_config(template.config)

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
                        file_dict[file].editable_blocks['constraint'][condition].modify(entry, change_list[file_num],
                                                                                        mod_pos,
                                                                                        species_type=block)
        else:
            keyword_dict = modified_params[block]
            block_name = CT_IDs[block][0]
            mod_pos = CT_IDs[block][1]
            for entry in keyword_dict:
                change_list = keyword_dict[entry]
                for file in file_dict:
                    file_num = file_dict[file].file_num
                    file_dict[file].editable_blocks[block_name].modify(entry, change_list[file_num], mod_pos)

    if not rhea:
        subprocess.run(['cp', f'{template.config["database"]}', f'{tmp_dir}/{template.config["database"]}'])

    if template.later_inputs:
        for file in file_dict:
            for key in file_dict[file].later_inputs:
                later_file = \
                    configure_input_files(file_dict[file].later_inputs[key], tmp_dir, rhea, file_dict[file].file_num)[0]
                file_dict[file].later_inputs.update({key: later_file})

    return file_dict


def add_restart_block(input_file, restart_index):


def get_config_array(spec, params, num_files, *, ref_vars=None):
    """Extract a value to assign from the config file.

    Args:
    entry -- A specific entry in a keyword block.
    config -- The config yaml file, as a dict.
    config_entry -- A top level dictionary entry in the config file, e.g. concetration, containing one or more species to be modified.
    file_num -- The number identifying the InputFile being modified.
    ref_vars -- The rest of the keyword block, in case it needs to be referred to. This is really just for the fix_ratio
                case and is a bit of a hot fix, as it doesn't work globally over the InputFile; i.e. you can only
                fix_ratio to other parameters in your KeywordBlock, or to species of the same type, e.g. an aqueous
                species or mineral etc.
    """
    import omphalos.parameter_methods as pm

    dispatch = {'linspace': pm.linspace,
                'random_uniform': pm.random_uniform,
                'constant': pm.constant,
                'custom': pm.custom_list,
                'fix_ratio': pm.fix_ratio
                }

    # Check to make sure the keyword is in the config_entry.
    # Look at first entry to determine behaviour.
    try:
        array = dispatch[spec](params, num_files)
    except KeyError:
        print('ConfigError: Unknown parameter setting. Abort.')
        import sys
        sys.exit()

    return array
