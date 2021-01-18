"""Script to run Omphalos inside slurm.
Expects command line args in order

dict_name -- name of the pickle file where the data has been stored as *.pickle
tmp_dir -- temporary directory for running input files. Must be unique.

"""
import argparse
import os
from context import omphalos
import omphalos.file_methods as fm
import omphalos.generate_inputs as gi
import omphalos.run as run
import omphalos.settings as settings

parser = argparse.ArgumentParser()
parser.add_argument("file_num", help="Input file dict key.")
parser.add_argument("timeout", help="Timeout for CT file.")
args = parser.parse_args()




print('Unpickle directory: tmp{}/input_file{}.pkl'.format(args.file_num, args.file_num))

input_file = fm.unpickle('tmp{}/input_file{}.pkl'.format(args.file_num, args.file_num))

print('Unpickle successful.')
print(os.getcwd())

input_file = run.run_input_file(input_file, args.file_num, 'tmp{}/'.format(args.file_num), args.timeout)


fm.pickle_data_set(input_file, 'tmp{}/input_file{}_complete.pkl'.format(args.file_num, args.file_num))
                         
print("File #{} completed".format(args.file_num))
