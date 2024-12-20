#!/bin/bash
#SBATCH --job-name=rhea_pre_run
#SBATCH --output=rhea_pre_run_%A.out

config_path=$CONFIG_PATH
database_name=$DATABASE_NAME
aqueous_database=$AQUEOUS_DATABASE
catabolic_pathways=$CATABOLIC_PATHWAYS
temperature_files=$TEMPERATURE_FILES
restart_file=$RESTART_FILE
pflotran=$PFLOTRAN

mkdir run${SLURM_ARRAY_TASK_ID}
cp ${database_name} run${SLURM_ARRAY_TASK_ID}/${database_name}

if [ "${pflotran}" ]; then
    cp ${restart_file} run${SLURM_ARRAY_TASK_ID}/${restart_file}
    if [ "${temperature_files}" ]; then
        for t_file in ${temperature_files[@]}; do
            cp ${t_file} run${SLURM_ARRAY_TASK_ID}/${t_file}
        done
    fi
else
    cp ${restart_file} run${SLURM_ARRAY_TASK_ID}/${restart_file}
    if [ "${aqueous_database}" ]; then
        cp ${aqueous_database} run${SLURM_ARRAY_TASK_ID}/${aqueous_database}
    fi
    if [ "${catabolic_pathways}" ]; then
        cp ${catabolic_pathways} run${SLURM_ARRAY_TASK_ID}/${catabolic_pathways}
    fi
    if [ "${temperature_files}" ]; then
        for t_file in ${temperature_files[@]}; do
            cp ${t_file} run${SLURM_ARRAY_TASK_ID}/${t_file}
        done
    fi
fi

exit 0

