# One-liner for script directory (for edge case where someone doesn't cd into Omphalos to run the install.
SCRIPT_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]:-$0}"; )" &> /dev/null && pwd 2> /dev/null; )";

if test -f "$HOME/.zshrc"; then
  printf "\n" >> $HOME/.zshrc
  echo \# Omphalos commands >> $HOME/.zshrc
  echo alias omphalos=\"python $SCRIPT_DIR/omphalos/main.py\" >> $HOME/.zshrc
  echo alias rhea=\"python $SCRIPT_DIR/rhea/main.py\" >> $HOME/.zshrc
  echo alias retrieval=\"python $SCRIPT_DIR/utils/retrieval_run.py\" >> $HOME/.zshrc
fi

if test -f "$HOME/.bashrc"; then
  printf "\n" >> $HOME/.bashrc
  echo \# Omphalos commands >> $HOME/.bashrc
  echo alias omphalos="python $SCRIPT_DIR/omphalos/main.py" >> $HOME/.bashrc
  echo alias rhea="python $SCRIPT_DIR/rhea/main.py" >> $HOME/.bashrc
  echo alias retrieval="python $SCRIPT_DIR/utils/retrieval_run.py" >> $HOME/.bashrc
fi