#!/bin/bash
#SBATCH --job-name=rhea_pre_run
#SBATCH --output=rhea_pre_run_%A.out

config_path=$CONFIG_PATH
database_name=$DATABASE_NAME
aqueous_database=$AQUEOUS_DATABASE
catabolic_pathways=$CATABOLIC_PATHWAYS
temperature_files=$TEMPERATURE_FILES
pflotran=$PFLOTRAN

mkdir run${SLURM_ARRAY_TASK_ID}
cp ${database_name} run${SLURM_ARRAY_TASK_ID}/

if [ "${pflotran}" ]; then
    :
else
    if [ "${aqueous_database}" ]; then
        cp ${aqueous_database} run${SLURM_ARRAY_TASK_ID}/
    fi
    if [ "${catabolic_pathways}" ]; then
        cp ${catabolic_pathways} run${SLURM_ARRAY_TASK_ID}/
    fi
    if [ "${temperature_files}" ]; then
        for t_file in ${temperature_files[@]}; do
            cp ${t_file} run${SLURM_ARRAY_TASK_ID}/
        done
    fi
fi

exit 0

