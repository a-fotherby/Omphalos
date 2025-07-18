
# One-liner for script directory (for edge case where someone doesn't cd into Omphalos to run the install.
SCRIPT_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]:-$0}"; )" &> /dev/null && pwd 2> /dev/null; )";

# Get user's default shell from passwd entry
USER_SHELL=$(basename "$SHELL")

# Get current shell basename
CURRENT_SHELL=$(ps -p $$ -o comm= | xargs basename)

if [ "$CURRENT_SHELL" != "$USER_SHELL" ]; then
  echo "Switching to user shell: $USER_SHELL to run the script..."

  # Re-exec script with user shell
  exec "$SHELL" "$0" "$@"
fi

echo "User's login shell: $USER_SHELL"

# Set alias definition
ALIAS_omphalos="alias omphalos=\"python $SCRIPT_DIR/omphalos/main.py\""
ALIAS_rhea="alias rhea=\"python $SCRIPT_DIR/rhea/main.py\""

# Determine config file
case "$USER_SHELL" in
    bash)
        CONFIG_FILE="$HOME/.bashrc"
        ;;
    zsh)
        CONFIG_FILE="$HOME/.zshrc"
        ;;
    *)
        echo "Unsupported or unknown shell: $USER_SHELL"
        exit 1
        ;;
esac

eval "$(conda shell.bash hook)"

conda config --add channels conda-forge
conda config --set channel_priority strict

conda env create --file requirements.yml

# Add alias if not already present
if grep -Fxq "$ALIAS_omphalos" "$CONFIG_FILE"; then
    echo "Alias already exists in $CONFIG_FILE"
else
    echo "$ALIAS_omphalos" >> "$CONFIG_FILE"
    echo "$ALIAS_rhea" >> "$CONFIG_FILE"
    echo "Alias added to $CONFIG_FILE"
fi

# Extract the path from the alias output
source $CONFIG_FILE
CT_PATH=$(which crunchtope 2>/dev/null | sed -n 's/^crunchtope: aliased to //p')

if [ -n "$CT_PATH" ]; then
    echo "CrunchTope path identified: $CT_PATH"
else
    echo "Failed to capture crunchtope alias"
    echo "Absolute path to CrunchTope executable:"
    read -r CT_PATH
fi

export SETTINGS="$SCRIPT_DIR/omphalos/settings.py"
touch "$SETTINGS"

echo >> "$SETTINGS"
echo '# Global settings for Omphalos' >> "$SETTINGS"
echo "crunch_dir = '$CT_PATH'" >> "$SETTINGS"
echo "omphalos_dir = '$SCRIPT_DIR'" >> "$SETTINGS"

source $CONFIG_FILE
