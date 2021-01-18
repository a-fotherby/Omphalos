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

parser = argparse.ArgumentParser()
parser.add_argument('path_to_config', type=str, help='YAML file containing options.')
args = parser.parse_args()

# Define procedual file genration name scheme at top for consistency.
# Do not change as this is not passed to slurm_exec.py
file_name_scheme = 'input_file'

with open(args.path_to_config) as file:
    config = yaml.full_load(file)

template = gi.import_template(config['template'])
file_dict = gi.configure_input_files(template, config)

for file in file_dict:
    path_to_file = 'tmp{}'.format(file)
    file_name = '{}{}.pkl'.format(file_name_scheme, file)
    fm.pickle_data_set(file_dict[file], file_name, path_to_file)
    subprocess.run(['cp', config['database'], '{}/{}'.format(path_to_file, config['database'])])
    if config['aqueous_database']:
        subprocess.run(['cp', config['aqueous_database'], '{}/{}'.format(path_to_file, config['aqueous_database'] )])

si.submit(file_dict, config['nodes'], config['timeout'])
