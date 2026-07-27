#!/bin/bash

# Runs a single input file, for GNU Parallel + srun to fan out over (see parallel.sbatch).
#
# $1 is the input file number, $2 the path to the config.
# OMPHALOS_DIR gives the location of this checkout; SLURM_SUBMIT_DIR is used if it is unset.

omphalos_dir=${OMPHALOS_DIR:-${SLURM_SUBMIT_DIR}}
python_exec=${OMPHALOS_PYTHON:-python}

if [ -z "${omphalos_dir}" ]; then
    echo "ERROR: neither OMPHALOS_DIR nor SLURM_SUBMIT_DIR is set; cannot locate slurm_exec.py" >&2
    exit 1
fi

task="${python_exec} ${omphalos_dir}/rhea/slurm_exec.py $1 $2"
$task

# $PARALLEL_SEQ is a special variable from GNU parallel, giving the number of the job in the
# sequence. Report where and when this task ran, for cross-referencing against runtask.log.
echo "$task" "seq:$PARALLEL_SEQ host:$(hostname) date:$(date)"
