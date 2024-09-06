#!/bin/bash 
#SBATCH --job-name=rhea
#SBATCH --output=rhea_%A_%a.out

#SBATCH --mem-per-cpu=2G  # NOTE DO NOT USE THE --mem= OPTION
#SBATCH --mail-type=END
#SBATCH --mail-user=af606@cam.ac.uk
#SBATCH --job-name="rhea"

# Load necessary modules (if required)
module load Python-bundle-PyPI/2023.06-GCCcore-12.3.0

config_path=$CONFIG_PATH
pflotran=$PFLOTRAN

# Use SLURM_ARRAY_TASK_ID to select the input file
python /home/af606/Omphalos/rhea/slurm_exec.py $SLURM_ARRAY_TASK_ID $config_path 

