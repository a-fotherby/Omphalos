"""Run Omphalos in parallel using Slurm.

Args:
config -- new option, specifies YAML file containing template modification options. Will replace 'condition' soon.

"""
import argparse
from context import omphalos
from omphalos.template import Template
import slurm_interface as si
import subprocess
import yaml
from time import time

parser = argparse.ArgumentParser()
parser.add_argument('path_to_config', type=str, help='YAML file containing options.')
args = parser.parse_args()

# Define procedural file generation name scheme at top for consistency.
# Do not change as this is not passed to slurm_exec.py
file_name_scheme = 'input_file'
dir_name = 'run'

with open(args.path_to_config) as file:
    config = yaml.full_load(file)

template = Template(config['template'])
file_dict = template.make_dict()

dict_size = len(file_dict)

t_start = time()

subprocess.run([f'parallel "mkdir {dir_name}{{1}}" ::: {{0..{dict_size}}}'], shell=True, executable='/bin/bash')
subprocess.run([f'parallel "cp {config["database"]} {dir_name}{{1}}/{config["database"]}" ::: {{0..{dict_size}}}'], shell=True, executable='/bin/bash')
                
for file in file_dict:
    file_dict[file].path = f'{dir_name}{file}/{file_name_scheme}.in'
    file_dict[file].print_input_file()

t_stop = time()

print(f'All files generated and directories prepped. Time elapsed: {t_stop-t_start}')

si.submit(args.path_to_config, config['nodes'], dict_size)