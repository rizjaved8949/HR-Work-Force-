from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from simulations.errors import SimulationValidationError
from simulations.repository import SimulationRepository
from simulations.schemas import ScenarioType, SimulationRequest
from simulations.service import SimulationService


def _service() -> SimulationService:
    repo_root = Path(__file__).resolve().parents[1]
    return SimulationService(SimulationRepository(repo_root / "Data"))


def test_employee_promotion_runs_without_mutating_data() -> None:
    service = _service()
    result = service.run(
        SimulationRequest(
            scenario_type=ScenarioType.EMPLOYEE_PROMOTION,
            employee_id="EMP002",
            target_position_id="POS-710",
        )
    )

    assert result.status == "completed"
    assert result.baseline["employee_id"] == "EMP002"
    assert result.baseline["current_job_level"] == "Mid"
    assert result.simulated_state["target_job_level"] == "Senior"
    assert result.simulated_state["target_position_available"] is True
    assert 0 <= result.impact["promotion_readiness_score_pct"] <= 100
    assert result.assumptions["mutates_source_data"] is False


def test_promotion_rejects_same_or_lower_level() -> None:
    service = _service()
    with pytest.raises(SimulationValidationError):
        service.run(
            SimulationRequest(
                scenario_type=ScenarioType.EMPLOYEE_PROMOTION,
                employee_id="EMP002",
                target_position_id="POS-016",  # Account Manager / Mid / same department
            )
        )


def test_promotion_rejects_cross_department_target() -> None:
    service = _service()
    with pytest.raises(SimulationValidationError):
        service.run(
            SimulationRequest(
                scenario_type=ScenarioType.EMPLOYEE_PROMOTION,
                employee_id="EMP002",
                target_position_id="POS-010",  # Engineering / Senior
            )
        )
