"""Conftest — add plugin root to sys.path for flat imports."""
import sys
from pathlib import Path

# Tests live at tests/, plugin root is one level up
PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))