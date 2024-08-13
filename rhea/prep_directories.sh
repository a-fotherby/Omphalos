#!/bin/bash
#SBATCH --job-name=rhea_pre_run
#SBATCH --output=rhea_pre_run_%A_%a.out

config_path = $CONFIG_PATH
database_name = $DATABASE_NAME
aqueous_database = $AQUEOUS_DATABASE
catabolic_pathways = $CATABOLIC_PATHWAYS
temperature_files = $TEMPERATURE_FILES
pflotran = $PFLOTRAN

mkdir run${SLURM_ARRAY_TASK_ID}
cp database_name run${SLURM_ARRAY_TASK_ID/database_name

if pflotran:
    pass
else:
    if aqueous_database:
            cp run${SLURM_ARRAY_TASK_ID}/aqueous_database
    if catabolic_pathways:
        cp catabolic_pathways run${SLURM_ARRAY_TASK_ID}}/catabolic_pathways
    if temperature_files:
        for t_file in "${temperature_files[@]}"
        do
            cp t_file run${SLURM_ARRAY_TASK_ID}/t_file
        done
