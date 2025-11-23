"""Context module for setting up the Python path.

This module ensures the parent package directory is in sys.path,
allowing imports from sibling packages (omphalos, pflotran, etc.).
"""

import sys
from pathlib import Path

# Add the parent directory (project root) to sys.path
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import omphalos
