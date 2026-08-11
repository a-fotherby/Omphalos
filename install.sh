
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

# Point git at the tracked hooks, so the README's test counts stay in step with the suite.
# Harmless if this is not a git checkout, hence the guard.
if git -C "$SCRIPT_DIR" rev-parse --git-dir > /dev/null 2>&1; then
    git -C "$SCRIPT_DIR" config core.hooksPath .githooks
    echo "Git hooks enabled from .githooks (see .githooks/update_test_counts.py)"
fi

export SETTINGS="$SCRIPT_DIR/omphalos/settings.py"
touch "$SETTINGS"

echo >> "$SETTINGS"
echo '# Global settings for Omphalos' >> "$SETTINGS"
echo "crunch_dir = '$CT_PATH'" >> "$SETTINGS"
echo "omphalos_dir = '$SCRIPT_DIR'" >> "$SETTINGS"

# Optional: MIN3P backend. Press Enter at either prompt to leave that entry as it
# is; both can also be set by editing min3p/settings.py (see settings_default.py).
export M3P_SETTINGS="$SCRIPT_DIR/min3p/settings.py"

# The file is rewritten whole below, so anything already in it that this run does
# not ask about has to be carried across -- otherwise skipping a prompt on a
# re-install would silently drop the other key.
M3P_OLD_BINARY=$(sed -n "s/^min3p_binary *= *['\"]\(.*\)['\"].*/\1/p" "$M3P_SETTINGS" 2>/dev/null)
M3P_OLD_EXAMPLES=$(sed -n "s/^min3p_examples *= *['\"]\(.*\)['\"].*/\1/p" "$M3P_SETTINGS" 2>/dev/null)

if [ -n "$M3P_OLD_BINARY" ]; then
    echo "Absolute path to MIN3P executable (Enter to keep $M3P_OLD_BINARY):"
else
    echo "Absolute path to MIN3P executable (optional, Enter to skip):"
fi
read -r M3P_PATH
[ -z "$M3P_PATH" ] && M3P_PATH="$M3P_OLD_BINARY"

# Only the tests need this: the round-trip tests in tests/unit/test_min3p.py parse
# the real benchmark decks and skip when they cannot be found. MIN3P_EXAMPLES in
# the environment takes precedence over whatever is written here.
if [ -n "$M3P_OLD_EXAMPLES" ]; then
    echo "Absolute path to MIN3P examples/benchmarks directory (Enter to keep $M3P_OLD_EXAMPLES):"
else
    echo "Absolute path to MIN3P examples/benchmarks directory (optional, Enter to skip):"
fi
read -r M3P_EXAMPLES
[ -z "$M3P_EXAMPLES" ] && M3P_EXAMPLES="$M3P_OLD_EXAMPLES"

if [ -n "$M3P_PATH" ] || [ -n "$M3P_EXAMPLES" ]; then
    echo '# Active MIN3P settings for this machine (git-ignored).' > "$M3P_SETTINGS"
    # Each key is written only if it has a value. An absent name raises ImportError
    # in the importers, which is exactly what their fallbacks catch.
    if [ -n "$M3P_PATH" ]; then
        echo "min3p_binary = '$M3P_PATH'" >> "$M3P_SETTINGS"
    fi
    if [ -n "$M3P_EXAMPLES" ]; then
        echo "min3p_examples = '$M3P_EXAMPLES'" >> "$M3P_SETTINGS"
    fi
    echo "MIN3P settings written to $M3P_SETTINGS"
fi

source $CONFIG_FILE
