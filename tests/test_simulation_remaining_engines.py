from pathlib import Path

from simulations import (
    ScenarioType,
    SimulationRepository,
    SimulationRequest,
    SimulationService,
)


DATA_DIR = Path(__file__).resolve().parents[1] / "Data"


def _service() -> SimulationService:
    return SimulationService(SimulationRepository(DATA_DIR))


def test_employee_transfer_engine_runs_without_mutating_source():
    result = _service().run(
        SimulationRequest(
            scenario_type=ScenarioType.EMPLOYEE_TRANSFER,
            employee_id="EMP003",
            target_department_id="DEPARTMENT-006",
            target_position_id="POS-730",
        )
    )
    assert result.status == "completed"
    assert result.simulated_state["organization_headcount_change"] == 0
    assert result.assumptions["mutates_source_data"] is False


def test_headcount_reduction_engine_runs():
    result = _service().run(
        SimulationRequest(
            scenario_type=ScenarioType.HEADCOUNT_REDUCTION,
            department_id="DEPARTMENT-002",
            parameters={"reduce_by": 5},
        )
    )
    assert result.simulated_state["reduce_by"] == 5
    assert result.simulated_state["simulated_headcount"] == result.baseline["current_headcount"] - 5


def test_workforce_expansion_engine_runs():
    result = _service().run(
        SimulationRequest(
            scenario_type=ScenarioType.WORKFORCE_EXPANSION,
            department_id="DEPARTMENT-002",
            parameters={"add_headcount": 3},
        )
    )
    assert result.simulated_state["add_headcount"] == 3
    assert result.simulated_state["simulated_headcount"] == result.baseline["current_headcount"] + 3


def test_budget_change_engine_runs():
    result = _service().run(
        SimulationRequest(
            scenario_type=ScenarioType.BUDGET_CHANGE,
            department_id="DEPARTMENT-002",
            parameters={"change_percentage": -10},
        )
    )
    assert result.simulated_state["change_percentage"] == -10
    assert result.simulated_state["simulated_people_budget_pkr"] < result.baseline["current_people_budget_pkr"]


def test_reskilling_engine_runs():
    result = _service().run(
        SimulationRequest(
            scenario_type=ScenarioType.SKILL_RESKILLING,
            employee_id="EMP003",
            parameters={"course_id": "COURSE-S027-PRC"},
        )
    )
    assert result.simulated_state["course_id"] == "COURSE-S027-PRC"
    assert result.assumptions["causal_claim"] is False


def test_business_demand_change_engine_runs():
    result = _service().run(
        SimulationRequest(
            scenario_type=ScenarioType.BUSINESS_DEMAND_CHANGE,
            department_id="DEPARTMENT-002",
            parameters={"demand_change_percentage": 25},
        )
    )
    assert result.simulated_state["demand_change_percentage"] == 25
    assert result.simulated_state["simulated_demand"] > result.baseline["current_demand"]
