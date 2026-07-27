#!/usr/bin/env bash

#SBATCH --mem-per-cpu=2G  # NOTE DO NOT USE THE --mem= OPTION
#SBATCH --job-name="rhea"

# Site-specific settings come from the environment rather than being hardcoded here.
# rhea/slurm_interface.submit() exports OMPHALOS_DIR, DICT_LEN and PATH_TO_CONFIG.
#
#   OMPHALOS_DIR     path to this checkout
#   OMPHALOS_PROFILE shell profile to source before running, e.g. "$HOME/.bashrc"
#   OMPHALOS_ENV     conda environment to activate (default: omphalos)
#   OMPHALOS_MODULES modules to load, space separated

omphalos_dir=${OMPHALOS_DIR:-${SLURM_SUBMIT_DIR}}

if [ -n "${OMPHALOS_PROFILE}" ] && [ -f "${OMPHALOS_PROFILE}" ]; then
    # shellcheck disable=SC1090
    source "${OMPHALOS_PROFILE}"
fi

for module_name in ${OMPHALOS_MODULES}; do
    module load "${module_name}"
done

source activate "${OMPHALOS_ENV:-omphalos}"

# When running a large number of tasks simultaneously, it may be
# necessary to increase the user process limit.
# ulimit -u 10000

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
$parallel "$srun ${omphalos_dir}/rhea/runtask.sh {1} {2} > runtask.sh.{1}" :::: <(seq 0 "$DICT_LEN") ::: "$PATH_TO_CONFIG"
