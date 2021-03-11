from context import omphalos

import numpy as np
import matplotlib as pyplot
import omphalos.file_methods as fm
import omphalos.input_file as ipf
import omphalos.generate_inputs as gi
import omphalos.run
import sys
import subprocess
import pickle
import argparse

parser = argparse.ArgumentParser()
parser.add_argument('path_to_config', type=str, help='YAML file containing options.')
parser.add_argument('output_name', type=str, help='Output file name.')
args = parser.parse_args()

dataset = gi.make_dataset(args.path_to_config)

# Pickle the data.
fm.pickle_data_set(dataset, '~/Omphalos/fitting/data/{}'.format(args.output_name))

