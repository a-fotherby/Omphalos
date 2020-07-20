"""Module for generating mutliple input files interatively, to make large data sets for testing."""
import numpy as np
import pandas as pd
import input_file as ipf
import file_methods as fm
import random as rand
import copy
import subprocess
import results

def import_template(file_path):
    """Import the template import file. Returns an input_file object, fully populated with all available keyword blocks.

    The template input file will define the mineral/species space of interest,
    as well as the geometry of the system in question.

    The child input files of the template will explore the mineral/species concentration space.
    Other special parameters such as temperature, diffusion, and advective flux can also be explored.

    The lists of species and minerals, as well as the system geometry/discretization remain unchanged.
    For this reason we are primarily focussed on iterating over the CONDITION blocks.
    """
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
        'INITIAL_CONDITIONS',
        'BOUNDARY_CONDITIONS',
        'TRANSPORT',
        'FLOW',
        'TEMPERATURE',
        'POROSITY',
        'PEST',
        'EROSION/BURIAL']
    for keyword in keyword_list:
        template.get_keyword_block(keyword)

    template.get_condition_blocks()

    return template


def create_condition_series(
        template,
        condition,
        number_of_files,
        var_min,
        var_max):
    """Create a dictionary of InputFile objects that have randomised parameters in the range [var_min, var_max] for the specified condition."""

    template.sort_condition_block(condition)

    keys = np.arange(number_of_files)

    file_dict = {}

    for key in keys:
        file_dict.update({key: copy.deepcopy(template)})

    for file in file_dict:
        for species in file_dict[file].condition_blocks[condition].primary_species.keys(
        ):
            file_dict[file].condition_blocks[condition].primary_species.update(
                {species: round(rand.uniform(var_min, var_max), 5)})

    return file_dict


def generate_data_set(template, condition, number_of_files, var_min, var_max):
    """Generates a dictionary of InputFile objects containing their results within a Results object.
    
    The input files have randomised initial conditions in one geochemical condition, specified by "condition".
    Each parameter in the randomised geochemical condition takes a random value on the interval [var_min, var_max].
    
    The directory specified by tmp_dir must already exist and be populated with the required databases, and otherwise be empty.
    """
    file_dict = create_condition_series(template, condition, number_of_files, var_min, var_max)
    for file_num, entry in enumerate(file_dict):
        # Print the file. Run it in CT. Collect the results, and assign to a Results object in the InputFile object.
        file_name = 'random' + str(file_num) + '.in'
        tmp_dir = 'tmp/'
        file_dict[entry].path = tmp_dir + file_name
        file_dict[entry].print_input_file()
        # Have to invoke absolute path for CT, this might vary by installation.
        subprocess.run(['/Users/angus/soft/crunchtope/CrunchTope', file_name], cwd = tmp_dir)
        
        # Make a results object that is an attribute of the InputFile object.
        file_dict[entry].results = results.Results()
        
        output_categories = fm.get_data_cats(tmp_dir)
        print(output_categories)
        
        for output in output_categories: 
            file_dict[entry].results.get_output(tmp_dir, output)
    
        # Clean the temp directory ready the next input file.
        subprocess.run(['rm', "*.tec"], cwd = tmp_dir)

    return file_dict
        
