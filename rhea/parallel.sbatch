#!/usr/bin/env bash

#SBATCH --mem-per-cpu=2G  # NOTE DO NOT USE THE --mem= OPTION
#SBATCH --mail-type=END
#SBATCH --mail-user=af606@cam.ac.uk

# Load the default version of GNU parallel.
# module load parallel

# When running a large number of tasks simultaneously, it may be
# necessary to increase the user process limit.
# ulimit -u 10000
# module load  parallel

# This specifies the options used to run srun. The "-N1 -n1" options are
# used to allocates a single core to each task.
srun="srun --exclusive -N1 -n1"

# This specifies the options used to run GNU parallel:
#
#   --delay of 0.2 prevents overloading the controlling node.
#
#   -j is the number of tasks run simultaneously.
#
#   The combination of --joblog and --resume create a task log that
#   can be used to monitor progress.
#
parallel="parallel --delay 1.0 -j $SLURM_NTASKS --joblog runtask.log --resume"

# Run a script, runtask.sh, using GNU parallel and srun. Parallel
# will run the runtask script for the numbers 1 through 128. To
# illustrate, the first job will run like this:
#
#   srun --exclusive -N1 -n1 ./runtask.sh arg1:1 > runtask.1
$parallel "$srun /home/af606/Omphalos/rhea/runtask.sh {1} {2} > runtask.sh.{1}" :::: <(seq 0 $DICT_LEN) ::: $PATH_TO_CONFIG
