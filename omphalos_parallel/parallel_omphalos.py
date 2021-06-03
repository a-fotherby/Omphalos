"""Run Omphalos in parallel using Slurm.

Args:
config -- new option, specifies YAML file containing template modification options. Will replace 'condition' soon.

"""
import argparse
from context import omphalos
import omphalos.generate_inputs as gi
import omphalos.file_methods as fm
import slurm_interface as si
import subprocess
import yaml

import numpy as np

parser = argparse.ArgumentParser()
parser.add_argument('path_to_config', type=str, help='YAML file containing options.')
args = parser.parse_args()

# Define procedural file generation name scheme at top for consistency.
# Do not change as this is not passed to slurm_exec.py
file_name_scheme = 'input_file'
dir_name = 'run'

with open(args.path_to_config) as file:
    config = yaml.full_load(file)

template = gi.import_template(config['template'])
file_dict = gi.configure_input_files(template, config)

dict_size = len(file_dict)

subprocess.run([f'parallel "mkdir {dir_name}{{1}}" ::: {{0..{dict_size}}}'], shell=True)
subprocess.run([f'parallel "cp {config["database"]} {dir_name}{{1}}/{config["database"]}" ::: {{0..{dict_size}}}'], shell=True)
                
if 'aqueous_database' in config:
    subprocess.run([f'parallel "cp {config["aqueous_database"]} {dir_name}{{1}}/{config["aqueous_database"]}" ::: {{0..{dict_size}}}'], shell=True)

# Legacy options for old CT input files that require them.
if 'catabolic_control' in config:
    subprocess.run([f'parallel "cp {config["catabolic_control"]} {dir_name}{{1}}/{config["catabolic_control"]}" ::: {{0..{dict_size}}}'], shell=True)
    subprocess.run([f'parallel "cp CatabolicControl.ant {dir_name}{{1}}/CatabolicControl.ant" ::: {{0..{dict_size}}}'], shell=True)
    
    
for file in file_dict:
    file_dict[file].path = f'{dir_name}{file}/{file_name_scheme}.in'
    file_dict[file].print_input_file()

si.submit(dict_size, config['nodes'], config['timeout'])
