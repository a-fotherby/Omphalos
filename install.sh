#!/usr/bin/bash

# One-liner for script directory (for edge case where someone doesn't cd into Omphalos to run the install.
SCRIPT_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]:-$0}"; )" &> /dev/null && pwd 2> /dev/null; )";

eval "$(conda shell.bash hook)"

conda config --add channels conda-forge
conda config --set channel_priority strict

conda create env --file requirements.yml

echo alias omphalos="$SCRIPT_DIR/omphalos/main.py" >> ~/.bashrc
echo alias rhea="$SCRIPT_DIR/rhea/main.py" >> ~/.bashrc

echo Absolute path to CrunchTope executable:
read -r CT_PATH

SETTINGS = "$SCRIPT_DIR/omphalos/settings.py"
touch $SETTINGS

echo '# Global settings for Omphalos' >> $SETTINGS
echo crunch_dir = \'"$CT_PATH"\' >> $SETTINGS
echo omphalos_dir = "$SCRIPT_DIR" >> $SETTINGS

source ~/.bashrc
