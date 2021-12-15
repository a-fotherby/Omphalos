"""Module for generating multiple input files iteratively, to make large data sets for testing."""

# Global var defining the relationship between keyword blocks and YAML file entries.
# Takes the form {'yaml_entry_name': [CRUNCHTOPE_KEYWORD, var_array_pos]}
CT_IDs = {'concentrations': ['geochemical condition', -1],
          'mineral_volumes': ['geochemical condition', 0],
          'parameters': ['geochemical condition', -1],
          'gases': ['geochemical condition', -1],
          'mineral_rates': ['MINERALS', -1],
          'aqueous_kinetics': ['AQUEOUS_KINETICS', -1],
          'flow': ['FLOW', 0],
          'transport': ['TRANSPORT', -1],
          'erosion/burial': ['EROSION/BURIAL', -1]
          }

CT_NMLs = {'aqueous': ['aqueous_database', 'Aqueous'],
           'aqueous_kinetics': ['aqueous_database', 'AqueousKinetics'],
           'catabolic_pathways': ['catabolic_pathways', 'CatabolicPathway']}


def configure_input_files(template):
    """Create a dictionary of InputFile objects that have randomised parameters in the range [var_min, var_max] for
    the specified condition. """

    for condition in template.config['conditions']:
        template.sort_condition_block(condition)

    file_dict = template.make_dict()

    for file in file_dict:
        for condition in template.config['conditions']:
            file_dict[file].sort_condition_block(condition)

        for config_param in CT_IDs:
            keyword = CT_IDs[config_param][0]
            mod_pos = CT_IDs[config_param][1]
            if keyword == 'geochemical condition':
                if config_param in template.config:
                    for condition in template.config[config_param]:
                        file_dict[file].condition_blocks[condition].modify(template.config, config_param, file_dict[file].file_num, mod_pos)
            else:
                if config_param in template.config:
                    file_dict[file].keyword_blocks[keyword].modify(file_dict[file].file_num, template.config, config_param, mod_pos)
        if 'namelist' in template.config:
            for nml_type in CT_NMLs:
                if nml_type in template.config['namelists']:
                    getattr(file_dict[file], CT_NMLs[nml_type][0]).modify_namelist(file_dict[file], template.config, nml_type)
                else:
                    pass
        else:
            pass
    return file_dict


def get_config_value(file_key, config, config_entry, file_num, ref_vars):
    """Extract a value to assign from the config file.

    Args:
    file_key -- A specific entry in a keyword block.
    config -- The config yaml file, as a dict.
    config_entry -- The index specifying the exact entry in the config file.
    file_num -- The number identifying the InputFile being modified.
    ref_vars -- The rest of the keyword block, in case it needs to be referred to. This is really just for the fix_ratio
                case and is a bit of a hot fix, as it doesn't work globally over the InputFile; i.e. you can only
                fix_ratio to other parameters in your KeywordBlock, or to species of the same type, e.g. an aqueous
                species or mineral etc.
    """
    import omphalos.parameter_methods as pm
    import omphalos.keyword_block as kwb
    import numpy as np

    if file_key in config_entry:
        # Look at first entry to determine behaviour.
        if config_entry[file_key][0] == 'linspace':
            lower = config_entry[file_key][1][0]
            upper = config_entry[file_key][1][1]
            interval_to_step = config_entry[file_key][1][2]
            value_to_assign = pm.linspace(lower, upper, config['number_of_files'], file_num,
                                          interval_to_step=interval_to_step)
        elif config_entry[file_key][0] == 'random_uniform':
            lower = config_entry[file_key][1][0]
            upper = config_entry[file_key][1][1]
            value_to_assign = np.random.uniform(lower, upper)
        elif config_entry[file_key][0] == 'constant':
            # Will overwrite default value from input file.
            value_to_assign = config_entry[file_key][1]
        elif config_entry[file_key][0] == 'custom':
            # Manually entered value list in config file must be same length as file_dict.
            value_to_assign = config_entry[file_key][1][file_num]
        elif config_entry[file_key][0] == 'fix_ratio':
            reference_var = config_entry[file_key][1]
            # Catch extra subscript indexing required for KeywordBlock.
            # This dict comparison is definitely a bad hack. Fix later.
            if type(ref_vars) == dict:
                reference_value = float(ref_vars[reference_var][-1])
            elif type(ref_vars) == kwb.KeywordBlock:
                reference_value = float(ref_vars.contents[reference_var][-1])
            else:
                Exception("You have somehow referenced a block object of unknown type. Aborting.")
            multiplier = config_entry[file_key][2]
            value_to_assign = reference_value * multiplier
        else:
            raise Exception("ConfigError: Unknown Omphalos parameter setting.")
        return value_to_assign
    else:
        # If the key in the input file is not in the list of species/reactions to be modified in the config file,
        # do nothing.
        return None
