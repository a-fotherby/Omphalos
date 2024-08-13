#!/bin/bash
#SBATCH --job-name=rhea
#SBATCH --output=rhea_%A_%a.out

config_path = $CONFIG_PATH
pflotran = $PFLOTRAN

# Use SLURM_ARRAY_TASK_ID to select input file
task="python /home/af606/Omphalos/rhea/slurm_exec.py pflotran $SLURM_ARRAY_TASK_ID config_path"
$task 
 
 
 
 