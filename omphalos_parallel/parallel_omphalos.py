"""Run Omphalos in parallel using Slurm.

Args:
template -- name of the template input file.
database -- name of the database.
condition -- condition to be altered: soon to be depreciated.
file_num -- number of files to generate.
data -- new option, specifies YAML file containing template modification options. Will replace 'condition' soon.

Optional args:
aqueous_database -- name of the aqueous database.
"""
import argparse
from context import omphalos
import omphalos.generate_inputs as gi
import omphalos.file_methods as fm
import slurm_interface as si
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument("template", type=str, help="Input file template name.")
parser.add_argument("database", type=str, help="Database file associated with the input file.")
parser.add_argument('aqueous_database', type=str, help='Aqueous database associated with the input file, if required.')
parser.add_argument('condition', type=str, help='Geochemical condition to be randomised.')
parser.add_argument('file_num', type=int, help='Number of input files to run.')
parser.add_argument('data', type=str, help='YAML file containing options.')
parser.add_argument('nodes', type=int, help='Number of CPUs on the slurm cluster to use.')
args = parser.parse_args()

# Define procedual file genration name scheme at top for consistency.
# Do not change as this is not passed to slurm_exec.py
file_name_scheme = 'input_file'

template = gi.import_template(args.template)

file_dict = gi.create_condition_series(
    template,
    args.condition,
    args.file_num,
    primary_species=True,
    mineral_volumes=False,
    mineral_rates=False,
    aqueous_rates=False,
    transports=False,
    data=args.data
    )

for file in file_dict:
    path_to_file = 'tmp{}'.format(file)
    file_name = '{}{}.pkl'.format(file_name_scheme, file)
    fm.pickle_data_set(file_dict[file], file_name, path_to_file)
    subprocess.run(['cp', args.database, '{}/{}'.format(path_to_file, args.database)])
    if args.aqueous_database:
        subprocess.run(['cp', args.aqueous_database, '{}/{}'.format(path_to_file, args.aqueous_database)])

si.submit(file_dict, args.nodes)
