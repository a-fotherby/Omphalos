"""Module for generating mutliple input files interatively, to make large data sets for testing."""
import numpy as np
import pandas as pd
import omphalos.input_file as ipf
import omphalos.file_methods as fm
import omphalos.results as results
import random as rand
import copy
import subprocess
import numpy.random as np_rand
import yaml

# Global var defining the realtionship between keyword blocks and YAML file entries.
# Takes the form {'yaml_entry_name': [CRUNCHTOPE_KEYWORD, var_array_pos]}
CT_IDs = {'concentrations': ['geochemical condition', -1],
          'mineral_volumes': ['geochemical condition', -1],
          'gases': ['geochemical condition', -1],
            'aqueous_kinetics': ['AQUEOUS_KINETICS', -1],
            'flow': ['FLOW', 1],
            'transport': ['TRANSPORT', -1]
}


def make_dataset(path_to_config):
    """Generates a dictionary of InputFile objects containing their results within a Results object.

    The input files have randomised initial conditions in one geochemical condition, specified by "condition".
    Each parameter in the randomised geochemical condition takes a random value on the interval [var_min, var_max].

    The directory specified by tmp_dir must already exist and be populated with the required databases.
    """
    import yaml
    import omphalos.run as run
    
    tmp_dir='tmp/'
    
    # Import config file.
    with open(path_to_config) as file:
        config = yaml.full_load(file)
        
    # Import template file.
    template = import_template(config['template'])
    # Get a dictionary of input files.
    print('*** Creating randomised input files ***')
    file_dict = configure_input_files(template, config)
    print('*** Begin running input files ***')
    run.run_dataset(file_dict, tmp_dir, config['timeout'])
    return file_dict

def import_template(file_path):
    """Import the template import file. Returns an input_file object, fully populated with all available keyword blocks.
    
    Args:
    file_path -- path to the CrunchTope input file.
    """
    print('*** Importing template file ***')
    template = ipf.InputFile(file_path)
    # Proceed to iterate through each keyword block to import the whole file.
    keyword_list = [
        'TITLE',
        'RUNTIME',
        'OUTPUT',
        'DISCRETIZATION',
        'PRIMARY_SPECIES',
        'SECONDARY_SPECIES',
        'GASES',
        'MINERALS',
        'AQUEOUS_KINETICS',
        'ION_EXCHANGE',
        'SURFACE_COMPLEXATION',
        'BOUNDARY_CONDITIONS',
        'TRANSPORT',
        'FLOW',
        'TEMPERATURE',
        'POROSITY',
        'PEST',
        'EROSION/BURIAL']
    for keyword in keyword_list:
        template.get_keyword_block(keyword)
    
    # Get=l keyword blocks that require unqiue handling due to format.
    template.get_initial_conditions_block()
    template.get_isotope_block()
    template.get_condition_blocks()

    return template

def configure_input_files(template, config):
    """Create a dictionary of InputFile objects that have randomised parameters in the range [var_min, var_max] for the specified condition."""
    for condition in config['conditions']:
        template.sort_condition_block(condition)

    file_dict = dict.fromkeys(np.arange(config['number_of_files']))

    for file_num in file_dict:
        file_dict[file_num] = copy.deepcopy(template)
        file_dict[file_num].file_num = file_num

    for file in file_dict:
        for condition in config['conditions']:
            file_dict[file].sort_condition_block(condition)
        if 'concentrations' in config:
            modify_condition_block(file_dict[file], config, 'concentrations')
        if 'mineral_volumes' in config:
            modify_condition_block(file_dict[file], config, 'mineral_volumes')
        if 'aqueous_kinetics' in config:
            modify_keyword_block(file_dict[file], config, 'aqueous_kinetics')
        if 'transport' in config:
            modify_keyword_block(file_dict[file], config, 'transport')
        if 'flow' in config:
            modify_keyword_block(file_dict[file], config, 'flow')

    return file_dict


def modify_condition_block(input_file, config, species_type):
        """Modify concentration based on config file.
        Requires its own method because multiple conditions may be specified."""
        mod_pos = CT_IDs[species_type][1]
    
        for condition in config[species_type]:
            condition_block_sec = {'concentrations': input_file.condition_blocks[condition].concentrations,
                                    'mineral_volumes': input_file.condition_blocks[condition].minerals,
                                    'gases': input_file.condition_blocks[condition].gases,
                                    'parameters': input_file.condition_blocks[condition].parameters}
            for species in condition_block_sec[species_type]:
                value_to_assign = get_config_value(species, config, config[species_type][condition], input_file.file_num)
                if value_to_assign == None:
                    continue
                file_value = condition_block_sec[species_type][species]
                file_value[mod_pos] = str(value_to_assign)
                condition_block_sec.update({species: file_value})
            
def modify_keyword_block(input_file, config, config_key, *, geochemical_condition=None):
    """Change the parameters of a keyword block in an InputFile object.
    
    Args:
    input_file -- The InputFile to be modified.
    config --  The config file dict containing the modifications to be made.
    config_key -- Key indexing which entry in the config file is in question.
    """
    import numpy as np
    
    # Extract corresponding input file block name and the position of the variable to be modified.
    CT_block_name = CT_IDs[config_key][0]
    mod_pos = CT_IDs[config_key][1]
    
    for file_key in input_file.keyword_blocks[CT_block_name].contents.keys():
        value_to_assign = get_config_value(file_key, config, config[config_key], input_file.file_num)
        if value_to_assign == None:
            continue
        file_value = input_file.keyword_blocks[CT_block_name].contents[file_key]
        file_value[mod_pos] = str(value_to_assign)
        input_file.keyword_blocks[CT_block_name].contents.update({file_key: file_value})
            

def get_config_value(file_key, config, config_entry, file_num):
    """Extract a value to assign from the config file."""
    import omphalos.parameter_methods as pm
    
    if file_key in config_entry:
        # Look at first entry to determine behaviour.
        if config_entry[file_key][0] == 'linspace':
            lower = config_entry[file_key][1][0]
            upper = config_entry[file_key][1][1]
            interval_to_step = config_entry[file_key][1][2]
            value_to_assign = pm.linspace(lower, upper, config['number_of_files'], file_num, interval_to_step=interval_to_step)
        elif config_entry[file_key][0] == 'random_uniform':
            lower = config_entry[file_key][1][0]
            upper = config_entry[file_key][1][1]
            value_to_assign = np.random.uniform(lower, upper)
        elif config_entry[file_key][0] == 'constant':
            # Will overwrite default value from input file.
            value_to_assign = config_entry[file_key][1]
        elif config_entry[file_key][0] == 'custom':
            # Manually entered value list in config file must be same length as file_dict.
            # Index offset by 1 because entry 0 is the keyword determining behaviour.
            value_to_assign = config_entry[file_key][file_num + 1]
        elif config_entry[file_key][0] == 'fix_ratio':
            reference_var = config_entry[file_key][1]
            reference_value = get_config_value(reference_var, config, config_entry, file_num)
            multiplier = config_entry[file_key][2]
            value_to_assign = reference_value * multiplier
        else:
            raise Exception("ConfigError: Unknown Omphalos parameter setting.")
        return value_to_assign
    else:
        # If the key in the input file is not in the list of species/reactions to be modified in the config file, do nothing.
        return None

    

