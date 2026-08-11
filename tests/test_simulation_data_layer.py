from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from simulations.repository import SimulationRepository
from simulations.service import SimulationDataService


def test_simulation_data_has_same_720_employees() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    repository = SimulationRepository(repo_root / "Data")
    report = repository.validate()

    assert report["employee_count"] == 720
    assert report["employee_feature_count"] == 720
    assert report["employee_ids_exact_match"] is True
    assert report["scenario_count"] == 7


def test_employee_context_joins_existing_and_new_data() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    service = SimulationDataService(SimulationRepository(repo_root / "Data"))

    context = service.get_employee_context("EMP004")

    assert context["employee"]["Employee_ID"] == "EMP004"
    assert context["simulation_features"]["Employee_ID"] == "EMP004"
    assert context["position"] is not None
    assert context["department_business"] is not None


def test_locked_seven_scenarios() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    service = SimulationDataService(SimulationRepository(repo_root / "Data"))
    scenarios = service.list_scenarios()

    codes = {row["Scenario_Code"] for row in scenarios}
    assert codes == {
        "employee_promotion",
        "employee_transfer",
        "headcount_reduction",
        "workforce_expansion",
        "budget_change",
        "skill_reskilling",
        "business_demand_change",
    }
