#!/bin/bash
#SBATCH --job-name=rhea_pre_run
#SBATCH --output=rhea_pre_run_%A.out

config_path=$CONFIG_PATH
database_name=$DATABASE_NAME
aqueous_database=$AQUEOUS_DATABASE
catabolic_pathways=$CATABOLIC_PATHWAYS
# Every spatial field CrunchTope reads from disk: porosity, saturation, temperature, tortuosity,
# permeability, flow, burial. Assembled by rhea/main.py from the template's read_*file keywords and
# from any per-stage files a restart_chain names, which appear in no template block.
aux_files=$AUX_FILES
restart_file=$RESTART_FILE
pflotran=$PFLOTRAN

run_dir=run${SLURM_ARRAY_TASK_ID}
mkdir ${run_dir}
cp ${database_name} ${run_dir}/${database_name}

if [ "${restart_file}" ]; then
    cp ${restart_file} ${run_dir}/${restart_file}
fi

# The aqueous database and catabolic pathways are CrunchTope-only; PFLOTRAN has neither.
if [ -z "${pflotran}" ]; then
    if [ "${aqueous_database}" ]; then
        cp ${aqueous_database} ${run_dir}/${aqueous_database}
    fi
    if [ "${catabolic_pathways}" ]; then
        cp ${catabolic_pathways} ${run_dir}/${catabolic_pathways}
    fi
fi

# Unquoted on purpose: AUX_FILES is a space-separated list and must word-split into one copy each.
# The relative path is kept rather than flattened, because CrunchTope opens the name exactly as the
# deck writes it, so 'data/porosity.dat' has to land in a 'data' subdirectory of the run.
for aux_file in ${aux_files}; do
    mkdir -p ${run_dir}/$(dirname ${aux_file})
    cp ${aux_file} ${run_dir}/${aux_file}
done

exit 0
