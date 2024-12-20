#!/bin/bash

# One-liner for script directory (for edge case where someone doesn't cd into Omphalos to run the install.
SCRIPT_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]:-$0}"; )" &> /dev/null && pwd 2> /dev/null; )";

eval "$(conda shell.bash hook)"

conda config --add channels conda-forge
conda config --set channel_priority strict

conda env create --file requirements.yml

echo alias omphalos="python $SCRIPT_DIR/omphalos/main.py" >> ~/.zshrc
echo alias rhea="python $SCRIPT_DIR/rhea/main.py" >> ~/.zshrc

echo Absolute path to CrunchTope executable:
read -r CT_PATH

echo >> $SCRIPT_DIR/omphalos/settings.py
export SETTINGS="$SCRIPT_DIR/omphalos/settings.py"
touch $SETTINGS

echo '# Global settings for Omphalos' >> $SETTINGS
echo crunch_dir = \'"$CT_PATH"\' >> $SETTINGS
echo omphalos_dir = \'"$SCRIPT_DIR"\' >> $SETTINGS

source ~/.zshrc
