#!/bin/bash
#SBATCH --job-name=rhea
#SBATCH --output=rhea_%A_%a.out

#SBATCH --mem-per-cpu=2G  # NOTE DO NOT USE THE --mem= OPTION
#SBATCH --nodes=1                      # Number of nodes
#SBATCH --ntasks=1                    # Total number of tasks (MPI processes)
#SBATCH --cpus-per-task=1              # Number of CPUs per task (for multi-threaded tasks)

# Site-specific settings are taken from the environment so this script does not need editing per
# machine. rhea/main.py exports OMPHALOS_DIR and CONFIG_PATH when it submits the array.
#
#   OMPHALOS_DIR     path to this checkout (exported by rhea/main.py)
#   OMPHALOS_MODULES modules to load, space separated, e.g.
#                    export OMPHALOS_MODULES="Python/3.10.8-GCCcore-12.2.0 OpenMPI/4.1.5-GCC-12.2.0"
#   OMPHALOS_PYTHON  python to run with (default: python)
#
# To be mailed on completion, add --mail-type/--mail-user to your sbatch invocation, or set them in
# a per-user ~/.slurm defaults file; they are deliberately not hardcoded here.

omphalos_dir=${OMPHALOS_DIR:-${SLURM_SUBMIT_DIR}}
config_path=$CONFIG_PATH
pflotran=$PFLOTRAN
python_exec=${OMPHALOS_PYTHON:-python}

if [ -z "${omphalos_dir}" ]; then
    echo "ERROR: neither OMPHALOS_DIR nor SLURM_SUBMIT_DIR is set; cannot locate slurm_exec.py" >&2
    exit 1
fi

# Load any modules the site needs.
for module_name in ${OMPHALOS_MODULES}; do
    module load "${module_name}"
done

# Use SLURM_ARRAY_TASK_ID to select the input file.
if [ "$pflotran" == "True" ]; then
    "${python_exec}" "${omphalos_dir}/rhea/slurm_exec.py" -p "$SLURM_ARRAY_TASK_ID" "$config_path"
else
    "${python_exec}" "${omphalos_dir}/rhea/slurm_exec.py" "$SLURM_ARRAY_TASK_ID" "$config_path"
fi
