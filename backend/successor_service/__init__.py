"""Local successor-recommendation service.

The backend folder is added to sys.path so `successor_service.config` can
import the shared `paths` module regardless of which directory the process
was started from.
"""

import sys
from pathlib import Path

_BACKEND_DIR = str(Path(__file__).resolve().parents[1])

if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)
