from pathlib import Path

from simulations.repository import SimulationRepository
from simulations.schemas import ScenarioType
from simulations.service import SimulationService
from simulations.tool import create_scenario_simulation_tool

DATA_PATH = Path("Data")


def _tool():
    service = SimulationService(SimulationRepository(DATA_PATH))
    return create_scenario_simulation_tool(service)


def test_scenario_tool_runs_headcount_reduction():
    result = _tool().invoke({
        "scenario_type": ScenarioType.HEADCOUNT_REDUCTION.value,
        "department_id": "DEPARTMENT-002",
        "parameters": {"reduce_by": 2},
    })
    assert result["status"] == "completed"
    assert result["scenario_type"] == ScenarioType.HEADCOUNT_REDUCTION.value


def test_scenario_tool_runs_employee_transfer():
    result = _tool().invoke({
        "scenario_type": ScenarioType.EMPLOYEE_TRANSFER.value,
        "employee_id": "EMP003",
        "target_department_id": "DEPARTMENT-006",
        "target_position_id": "POS-730",
        "parameters": {},
    })
    assert result["status"] == "completed"
    assert result["resolved_inputs"]["employee_id"] == "EMP003"


def test_scenario_tool_runs_reskilling():
    result = _tool().invoke({
        "scenario_type": ScenarioType.SKILL_RESKILLING.value,
        "employee_id": "EMP003",
        "course_id": "COURSE-S027-PRC",
        "parameters": {},
    })
    assert result["status"] == "completed"
    assert result["resolved_inputs"]["course_id"] == "COURSE-S027-PRC"


def test_scenario_tool_returns_clarification_for_missing_inputs():
    result = _tool().invoke({
        "scenario_type": ScenarioType.BUDGET_CHANGE.value,
        "department": "Finance",
        "parameters": {},
    })
    assert result["status"] == "needs_clarification"
    assert "parameters.change_percentage" in result["missing_fields"]
