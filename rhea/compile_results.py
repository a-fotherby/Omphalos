import slurm_interface as si
import argparse

# import matplotlib
# matplotlib.use('Agg')

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("dict_len", type=int, help="Length of dictionary to create/compile.")
    args = parser.parse_args()

    si.compile_results(args.dict_len)
