"""Standalone fixture helper for the Performance code package.

Copy the fixture below into your project's tests/conftest.py, or rename this
file to conftest.py if the project does not already have one.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest


@pytest.fixture
def performance_data_dir(tmp_path: Path) -> Path:
    """Build an isolated read-only-style Data fixture from the repository Data folder."""

    repo_root = Path(__file__).resolve().parents[1]
    source = repo_root / "Data"
    target = tmp_path / "Data"
    target.mkdir()

    required = [
        "Employee_Profile.csv",
        "Performance_Role_Mapping.csv",
        "KPI_Catalog.csv",
        "Role_KPI_Template.csv",
        "Employee_KPI_Assignment.csv",
        "Employee_Performance_Evidence_Monthly.csv",
        "Employee_Performance_Monthly.csv",
        "Employee_Performance_Summary.csv",
        "Department_Performance_Monthly.csv",
        "Employee_Skills.csv",
        "Skill_Catalog.csv",
        "Position_Skill_Requirements.csv",
        "Learning_Course_Catalog.csv",
        "KPI_Skill_Development_Map.csv",
        "Skill_Course_Mapping.csv",
        "Employee_Learning_History.csv",
        "Employee_Development_Recommendation.csv",
        "Employee_Learning_Profile_Summary.csv",
        "Learning_Data_Quality_Report.csv",
    ]

    for filename in required:
        source_file = source / filename
        if not source_file.is_file():
            pytest.fail(
                f"Performance test data file is missing: {source_file}. "
                "Copy the Performance and Learning CSV package into the shared Data folder first."
            )
        shutil.copy2(source_file, target / filename)

    return target
