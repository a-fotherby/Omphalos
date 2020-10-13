"""Module for generating mutliple input files interatively, to make large data sets for testing."""
import numpy as np
import pandas as pd
import input_file as ipf
import file_methods as fm
import random as rand
import copy
import subprocess
import results
import signal


def import_template(file_path):
    """Import the template import file. Returns an input_file object, fully populated with all available keyword blocks.

    The template input file will define the mineral/species space of interest,
    as well as the geometry of the system in question.

    The child input files of the template will explore the mineral/species concentration space.
    Other special parameters such as temperature, diffusion, and advective flux can also be explored.

    The lists of species and minerals, as well as the system geometry/discretization remain unchanged.
    For this reason we are primarily focussed on iterating over the CONDITION blocks.
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

    template.get_initial_conditions_block()
    template.get_isotope_block()
    template.get_condition_blocks()

    return template


def create_condition_series(
        template,
        condition,
        number_of_files,
        *,
        primary_species=False,
        mineral_volumes=False,
        mineral_rates=False
):
    """Create a dictionary of InputFile objects that have randomised parameters in the range [var_min, var_max] for the specified condition."""

    template.sort_condition_block(condition)

    keys = np.arange(number_of_files)

    file_dict = {}

    for key in keys:
        file_dict.update({key: copy.deepcopy(template)})

    for file in file_dict:
        if primary_species:
            concentrations(file_dict[file], condition)
        else:
            pass

        if mineral_volumes:
            minerals_volumes(file_dict[file], condition, 0.9)
        else:
            pass

    return file_dict


def concentrations(input_file, condition, mean_recip):
    for species in input_file.condition_blocks[condition].primary_species.keys(
    ):
        default_conc = input_file.condition_blocks[condition].primary_species[species][0]
        # Quick and dirty fix - can't have charge in DataFrame as is string, so need to approximate the calculated value. Na+ will do for now.
        if default_conc == 'charge':
            default_conc = input_file.condition_blocks[condition].primary_species['Na+'][0]
        else:
            default_conc = float(default_conc)
            
        # Quick fix for mean recip parameter in exponential distribution.
        default_conc = 1 / default_conc
        
        if species == 'Ca++':
            #ca_conc = round(rand.gauss(default_val, 1), 15)
            ca_conc = round(rand.expovariate(default_conc), 15)
            ca44_conc = ca_conc * 0.021226645
            input_file.condition_blocks[condition].primary_species.update(
                {species: [ca_conc]})
            input_file.condition_blocks[condition].primary_species.update(
                {'Ca44++': [ca44_conc]})
        elif species == 'Ca44++':
            pass
        elif species == 'SO4--':
            #s_conc = round(rand.gauss(default_val, 1), 15)
            s_conc = round(rand.expovariate(default_conc), 15)
            s34_conc = s_conc * 0.0450900146
            input_file.condition_blocks[condition].primary_species.update(
                {species: [s_conc]})
            input_file.condition_blocks[condition].primary_species.update(
                {'S34O4--': [s34_conc]})
        elif species == 'S34O4--':
            pass
        else:
            #input_file.condition_blocks[condition].primary_species.update(
            #{species: [round(rand.gauss(default_val, 1), 15)]})
            input_file.condition_blocks[condition].primary_species.update(
                {species: [round(rand.expovariate(default_conc), 15)]})


def minerals_volumes(input_file, condition, total_volume):
    """Randomise mineral volume fractions in a data_set of InputFiles.

    Total volume must be less than exactly 1 or CrunchTope wont run: 0.9999 is acceptable.
    """
    # First ensure that the sum total of mineral volume fractions is less than 1.
    # Use the Dirichlet function to provide a list of numbers that sum to 1 on the interval [0,1].
    # The Dirichlet function is very flexible; in it's symmetric (i.e. all entries in input vectors the same - in which case we call that single value the concentration parameter)
    # case no returned value will be biased larger than the others, and in the case that the concentration parameter is 1, the entries will all be drawn from a uniform distribution.
    # In the case that conc_param > 1, values returned will be more similar.
    # If conc_param < 1 then the the values will be less similar.
    mineral_num = len(input_file.condition_blocks[condition].minerals)
    alpha = np.ones(mineral_num)
    
    volume_fractions = np.random.dirichlet(alpha) * total_volume
    
    
    for mineral, volume_frac in zip(input_file.condition_blocks[condition].minerals.keys(), volume_fractions):
        if mineral == 'Calcite':
            entry = input_file.condition_blocks[condition].minerals[mineral]
            entry[0] = volume_frac
            input_file.condition_blocks[condition].minerals.update(
                {mineral: entry})
            entry_44 = input_file.condition_blocks[condition].minerals['Calcite44']
            entry_44[0] = volume_frac * 0.02120014696
            input_file.condition_blocks[condition].minerals.update({'Calcite44': entry_44})

        else:
            entry = input_file.condition_blocks[condition].minerals[mineral]
            input_file.condition_blocks[condition].minerals.update({mineral: entry})

def generate_data_set(template, condition, number_of_files, name):
    """Generates a dictionary of InputFile objects containing their results within a Results object.

    The input files have randomised initial conditions in one geochemical condition, specified by "condition".
    Each parameter in the randomised geochemical condition takes a random value on the interval [var_min, var_max].

    The directory specified by tmp_dir must already exist and be populated with the required databases.
    """
    # Get a dictionary of input files. Set the randomisation options here.
    # !!!
    # !!! Randomisation options !!!
    # !!!
    print('*** Creating randomised input files ***')
    file_dict = create_condition_series(
        template,
        condition,
        number_of_files,
        primary_species=True,
        mineral_volumes=True,
        mineral_rates=False)
    print('*** Begin running input files ***')
    
    timeout_list = []
    for file_num, entry in enumerate(file_dict):
        # Print the file. Run it in CT. Collect the results, and assign to a
        # Results object in the InputFile object.
        file_name = name + str(file_num) + '.in'
        out_file_name = name + str(file_num) + '.out'
        tmp_dir = 'tmp/'
        file_dict[entry].path = tmp_dir + file_name
        file_dict[entry].print_input_file()
        
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(60)
        try:
            run_crunchtope(file_name, tmp_dir)
        except Exception: 
            print('File {} timed out.'.format(file_num))
            timeout_list.append(file_num)
            # Clean the temp directory ready the next input file.
            subprocess.run(['rm', "*.tec"], cwd=tmp_dir)
            subprocess.run(['rm', file_name], cwd=tmp_dir)
            subprocess.run(['rm', out_file_name], cwd=tmp_dir)
            continue
        
        signal.alarm(0)
    
        # Make a results object that is an attribute of the InputFile object.
        file_dict[entry].results = results.Results()

        output_categories = fm.get_data_cats(tmp_dir)
        for output in output_categories:
            file_dict[entry].results.get_output(tmp_dir, output)

        # Clean the temp directory ready the next input file.
        subprocess.run(['rm', "*.tec"], cwd=tmp_dir)
        subprocess.run(['rm', file_name], cwd=tmp_dir)
        subprocess.run(['rm', out_file_name], cwd=tmp_dir)
        
        print('File {} complete.'.format(file_num))

    for file_num in timeout_list:
        file_dict.pop(file_num)

    return file_dict

def run_crunchtope(file_name, tmp_dir):
    # Have to invoke absolute path for CT, this might vary by installation.
    subprocess.run(['/Users/angus/soft/crunchtope/CrunchTope', file_name], cwd=tmp_dir)

def timeout_handler(signum, frame):
    raise Exception("CrunchTimeout")