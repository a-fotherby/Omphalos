"""Module for generating mutliple input files interatively, to make large data sets for testing."""
import numpy as np
import pandas as pd
import input_file as ipf
import file_methods as fm


def import_template(file_path):
    """Import the template import file.
    
    The template input file will define the mineral/species space of interest,
    as well as the geometry of the system in question. 
    
    The child input files of the template will explore the mineral/species concentration space.
    Other special parameters such as temperature, diffusion, and advective flux can also be explored.
    
    The lists of species and minerals, as well as the system geometry/discretization remain unchanged.
    For this reason we are primarily focussed on iterating over the CONDITION blocks.
    """
    template = ipf.InputFile(file_path)
    # Proceed to iterate through each keyword block to import the whole file.
    keyword_list = ['TITLE', 'RUNTIME', 'OUTPUT', 'DISCRETIZATION', 'PRIMARY_SPECIES', 'SECONDARY_SPECIES', 'GASES', 'MINERALS', 'AQUEOUS_KINETICS', 'ION_EXCHANGE', 'SURFACE_COMPLEXATION', 'INITIAL_CONDITIONS', 'BOUNDARY_CONDITIONS', 'TRANSPORT', 'FLOW', 'TEMPERATURE', 'POROSITY', 'PEST', 'EROSION/BURIAL']
    for keyword in keyword_list:
        template.get_keyword_block(keyword)
        
    template.get_condition_blocks()
    
    return template

    
    
    