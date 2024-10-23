#!/bin/bash 
#SBATCH --job-name=rhea
#SBATCH --output=rhea_%A_%a.out

#SBATCH --mem-per-cpu=2G  # NOTE DO NOT USE THE --mem= OPTION
#SBATCH --mail-type=END
#SBATCH --mail-user=af606@cam.ac.uk
#SBATCH --job-name="rhea"
#SBATCH --nodes=1                      # Number of nodes
#SBATCH --ntasks=1                    # Total number of tasks (MPI processes)
#SBATCH --cpus-per-task=1              # Number of CPUs per task (for multi-threaded tasks)

# Load necessary modules (if required)
module load Python/3.10.8-GCCcore-12.2.0
module load METIS/5.1.0-GCCcore-12.2.0
module load XZ/5.2.7-GCCcore-12.2.0
module load OpenMPI/4.1.5-GCC-12.2.0

config_path=$CONFIG_PATH
pflotran=$PFLOTRAN

if [ "$pflotran" == "True" ]; then
    python /home/af606/Omphalos/rhea/slurm_exec.py -p $SLURM_ARRAY_TASK_ID $config_path
else
    python /home/af606/Omphalos/rhea/slurm_exec.py $SLURM_ARRAY_TASK_ID $config_path
fi
# Use SLURM_ARRAY_TASK_ID to select the input file

