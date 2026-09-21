"""Single source of truth for every filesystem path used by the backend.

Nothing in this project may hardcode an absolute drive path. Every module
resolves its paths from here, so the repository can be cloned anywhere.
"""

from __future__ import annotations

import os
from pathlib import Path

# .../Attrition_Project/backend/paths.py
BACKEND_DIR = Path(__file__).resolve().parent

# .../Attrition_Project
REPO_ROOT = BACKEND_DIR.parent

# The single .env file for the whole project.
ENV_FILE = REPO_ROOT / ".env"


def _from_env(variable_name: str, default: Path) -> Path:
    """Read a path from the environment, falling back to a repo-relative default.

    Relative values in .env are resolved against the repository root so the
    same .env works on every machine.
    """

    raw_value = os.getenv(variable_name)

    if not raw_value or not raw_value.strip():
        return default

    candidate = Path(raw_value.strip()).expanduser()

    return candidate if candidate.is_absolute() else REPO_ROOT / candidate


def data_dir() -> Path:
    """Shared CSV folder used by both the attrition and successor workflows."""

    return _from_env("DATA_DIR", REPO_ROOT / "Data")


def model_path() -> Path:
    """Saved CatBoost attrition model."""

    return _from_env(
        "MODEL_PATH",
        REPO_ROOT / "models" / "catboost_attrition_model.cbm",
    )
