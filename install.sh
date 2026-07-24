
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
        CONFIG_FILE="$HOME/.bash_profile"
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

# Add each alias if not already present, independently, so re-running install
# picks up any newly-added command on an existing installation.
for alias_def in "$ALIAS_omphalos" "$ALIAS_rhea"; do
    if grep -Fxq "$alias_def" "$CONFIG_FILE" 2>/dev/null; then
        echo "Alias already present: $alias_def"
    else
        echo "$alias_def" >> "$CONFIG_FILE"
        echo "Alias added: $alias_def"
    fi
done

# Extract the path from the alias output
source $CONFIG_FILE
CT_PATH=$(which crunchtope 2>/dev/null | sed -e 's/^crunchtope: aliased to //' | xargs)

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

# Optional: MIN3P backend executable. Press Enter to skip (you can set it later
# via min3p/settings.py or per-run with the config key `min3p_binary`).
echo "Absolute path to MIN3P executable (optional, Enter to skip):"
read -r M3P_PATH
if [ -n "$M3P_PATH" ]; then
    export M3P_SETTINGS="$SCRIPT_DIR/min3p/settings.py"
    echo '# Active MIN3P settings for this machine (git-ignored).' > "$M3P_SETTINGS"
    echo "min3p_binary = '$M3P_PATH'" >> "$M3P_SETTINGS"
    echo "MIN3P path written to $M3P_SETTINGS"
fi

source $CONFIG_FILE
