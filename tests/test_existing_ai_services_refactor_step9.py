from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from attrition_prediction_tool import AttritionPredictor
from feature_resolution.service import FeatureResolutionService
from graph.memory_repository import InMemoryGraphRepository
from graph.service import GRAPH_MODEL_SERVICE
from semantic.service import SemanticHRService
from service_refactor.attrition import GraphAttritionPredictionService
from service_refactor.config import Step9RuntimeConfig
from service_refactor.employee import GraphEmployeeRecordService
from service_refactor.models import RuntimeMode
from service_refactor.router import create_step9_runtime_router
from service_refactor.runtime import Step9RuntimeManager


ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / "models" / "catboost_attrition_model.cbm"


def _node(repo, entity_type: str, properties: dict[str, Any], key: str):
    node = GRAPH_MODEL_SERVICE.create_node(
        tenant_id="ORG-1",
        entity_type=entity_type,
        properties=properties,
        source_system="step9-test",
        source_object=entity_type,
        source_record_key=key,
        mapping_version="step9-test",
    )
    repo.upsert_node(node)
    return node


def _edge(repo, source, relation: str, target, key: str):
    edge = GRAPH_MODEL_SERVICE.create_relationship(
        tenant_id="ORG-1",
        relation_type=relation,
        source_node=source,
        target_node=target,
        source_system="step9-test",
        source_object="relationship",
        source_record_key=key,
        mapping_version="step9-test",
    )
    repo.upsert_relationship(edge)
    return edge


def _seed_repo() -> InMemoryGraphRepository:
    repo = InMemoryGraphRepository()

    org = _node(repo, "Organization", {"organizationId": "ORG-1", "name": "Example Org"}, "org")
    bu = _node(repo, "BusinessUnit", {"businessUnitId": "BU-1", "name": "Technology"}, "bu")
    dept = _node(repo, "Department", {"departmentId": "D-1", "name": "AI"}, "dept")
    ou = _node(repo, "OrganizationalUnit", {"organizationalUnitId": "OU-1", "name": "AI Lab", "unitType": "Team"}, "ou")
    loc = _node(repo, "WorkLocation", {"workLocationId": "L-1", "name": "Lahore HQ", "city": "Lahore"}, "loc")
    cc = _node(repo, "CostCenter", {"costCenterId": "CC-1", "name": "AI Cost", "currency": "PKR"}, "cc")
    position = _node(
        repo,
        "Position",
        {
            "positionId": "P-1",
            "title": "ML Engineer",
            "designation": "Senior ML Engineer",
            "jobLevel": "L3",
            "positionStatus": "Filled",
            "approvedPosition": True,
            "budgetedPosition": True,
        },
        "position",
    )
    reporting_position = _node(
        repo,
        "Position",
        {
            "positionId": "P-0",
            "title": "AI Director",
            "designation": "Director AI",
            "jobLevel": "L4",
            "positionStatus": "Filled",
            "approvedPosition": True,
            "budgetedPosition": True,
        },
        "reporting-position",
    )
    position_budget = _node(
        repo,
        "PositionBudget",
        {
            "positionBudgetId": "PB-1",
            "fiscalYear": 2026,
            "annualSalaryBudget": 1500000,
            "annualBenefitsBudget": 250000,
            "dataAsOfDate": "2026-03-15",
        },
        "position-budget",
    )
    vacancy = _node(
        repo,
        "VacancyRecord",
        {
            "vacancyRecordId": "VAC-1",
            "vacancyStartDate": "2025-12-01",
            "vacancyStatus": "Closed",
            "dataAsOfDate": "2026-03-15",
        },
        "vacancy",
    )
    employee = _node(repo, "Employee", {"employeeId": "E-1", "name": "Ali Khan"}, "employee")
    manager = _node(repo, "Employee", {"employeeId": "E-2", "name": "Sara Manager"}, "manager")
    employment = _node(
        repo,
        "Employment",
        {
            "jobLevel": "L3",
            "workMode": "Hybrid",
            "shiftType": "Day",
            "employmentType": "Permanent",
            "employeeStatus": "Active",
            "tenureMonths": 14,
            "yearsInCompany": 1.17,
            "hireDate": "2025-01-15",
            "dataAsOfDate": "2026-03-15",
            "careerLevel": "Professional",
            "employeeCategory": "Staff",
            "headcountInclusionCategory": "Core",
            "includedInApprovedHeadcount": True,
            "standardWeeklyHours": 40,
        },
        "employment",
    )
    assignment = _node(
        repo,
        "Assignment",
        {"assignmentId": "A-1", "status": "Current", "startDate": "2025-01-15", "fullTimeEquivalent": 1.0},
        "assignment",
    )
    compensation = _node(
        repo,
        "CompensationRecord",
        {
            "monthlyAmount": 120000,
            "salaryVsMarketPercentage": -5.5,
            "lastIncrementPercentage": 8.0,
            "payConcernRaisedLast6Months": True,
        },
        "comp",
    )
    performance = _node(
        repo,
        "PerformanceRecord",
        {
            "assessmentPeriod": "2026-03",
            "kpiAchievementPercentage": 92.0,
            "performanceTrend6M": 3.5,
            "performanceScore": 91,
            "performanceBand": "Strong",
            "managerRating": 4.4,
        },
        "perf",
    )
    attendance = _node(
        repo,
        "AttendanceRecord",
        {
            "attendancePeriod": "2026-03",
            "overtimeHoursLast30Days": 12.0,
            "absenceDaysLast90Days": 1,
            "attendanceScore": 97,
            "dataAsOfDate": "2026-03-15",
        },
        "attendance",
    )
    engagement = _node(
        repo,
        "EngagementRecord",
        {
            "engagementScore": 4.1,
            "jobSatisfactionScore": 4.0,
            "workLifeBalanceScore": 3.8,
            "managerRelationshipScore": 4.2,
            "careerGrowthScore": 3.9,
            "dataAsOfDate": "2026-03-15",
        },
        "engagement",
    )
    experience = _node(
        repo,
        "ExperienceProfile",
        {
            "monthsSinceLastPromotion": 7,
            "totalExperienceYears": 6,
            "relevantExperienceYears": 5,
            "yearsInCurrentRole": 1.2,
            "experienceScore": 88,
        },
        "experience",
    )
    readiness = _node(
        repo,
        "SuccessionReadiness",
        {"candidateBaseEligibility": "Yes", "internalMobilityReadiness": "Ready"},
        "readiness",
    )
    requirement = _node(
        repo,
        "PositionRequirement",
        {"minimumTotalExperienceYears": 4, "leadershipRequired": "Preferred"},
        "requirement",
    )
    skill = _node(repo, "Skill", {"skillId": "S-1", "name": "Python", "category": "Technical", "skillType": "Hard"}, "skill")
    employee_skill = _node(
        repo,
        "EmployeeSkill",
        {"proficiencyLevel": 4, "skillScore": 90, "isPrimarySkill": True},
        "employee-skill",
    )
    position_skill = _node(
        repo,
        "PositionSkillRequirement",
        {"requirementType": "Required", "mandatory": True, "minimumProficiencyLevel": 3},
        "position-skill",
    )

    _edge(repo, org, "HAS_BUSINESS_UNIT", bu, "org-bu")
    _edge(repo, bu, "HAS_DEPARTMENT", dept, "bu-dept")
    _edge(repo, dept, "HAS_ORGANIZATIONAL_UNIT", ou, "dept-ou")
    _edge(repo, dept, "PRIMARY_LOCATION", loc, "dept-loc")
    _edge(repo, dept, "USES_COST_CENTER", cc, "dept-cc")
    _edge(repo, employee, "HAS_EMPLOYMENT", employment, "employee-employment")
    _edge(repo, employee, "HAS_ASSIGNMENT", assignment, "employee-assignment")
    _edge(repo, assignment, "TO_POSITION", position, "assignment-position")
    _edge(repo, position, "REPORTS_TO_POSITION", reporting_position, "position-reporting")
    _edge(repo, position, "HAS_BUDGET", position_budget, "position-budget-edge")
    _edge(repo, position, "HAS_VACANCY", vacancy, "position-vacancy-edge")
    _edge(repo, assignment, "IN_DEPARTMENT", dept, "assignment-dept")
    _edge(repo, assignment, "IN_ORGANIZATIONAL_UNIT", ou, "assignment-ou")
    _edge(repo, assignment, "AT_LOCATION", loc, "assignment-loc")
    _edge(repo, assignment, "CHARGED_TO", cc, "assignment-cc")
    _edge(repo, employee, "REPORTS_TO", manager, "reports")
    _edge(repo, employee, "HAS_COMPENSATION", compensation, "employee-comp")
    _edge(repo, employee, "HAS_PERFORMANCE_RECORD", performance, "employee-perf")
    _edge(repo, employee, "HAS_ATTENDANCE_RECORD", attendance, "employee-att")
    _edge(repo, employee, "HAS_ENGAGEMENT_RECORD", engagement, "employee-eng")
    _edge(repo, employee, "HAS_EXPERIENCE_PROFILE", experience, "employee-exp")
    _edge(repo, employee, "HAS_SUCCESSION_READINESS", readiness, "employee-ready")
    _edge(repo, position, "HAS_REQUIREMENT", requirement, "position-req")
    _edge(repo, employee, "HAS_SKILL", employee_skill, "employee-skill-edge")
    _edge(repo, employee_skill, "OF_SKILL", skill, "employee-skill-type")
    _edge(repo, position, "REQUIRES_SKILL", position_skill, "position-skill-edge")
    _edge(repo, position_skill, "OF_SKILL", skill, "position-skill-type")
    return repo


class _FakeTool:
    def __init__(self, payload: dict[str, Any]):
        self.payload = payload

    def invoke(self, arguments: dict[str, Any]):
        return dict(self.payload)


def _services():
    semantic = SemanticHRService(_seed_repo())
    features = FeatureResolutionService(semantic)
    return semantic, features


def test_step9_employee_search_builds_legacy_ui_shape_from_graph():
    semantic, _ = _services()
    service = GraphEmployeeRecordService(semantic, tenant_id="ORG-1")
    result = service.get_by_employee_id("E-1")
    assert result["status"] == "found"
    assert result["employee"]["employee_name"] == "Ali Khan"
    assert result["employee"]["department"] == "AI"
    assert result["employee"]["office"] == "Lahore HQ"
    assert result["records"]["profile"]["Employee_ID"] == "E-1"
    assert result["records"]["profile"]["Manager_Employee_ID"] == "E-2"
    assert result["records"]["attrition_features"]["Monthly_Salary_PKR"] == 120000
    assert result["records"]["profile"]["Included_in_Approved_Headcount"] == "Yes"
    assert result["records"]["skills"][0]["Skill_ID"] == "S-1"
    assert result["records"]["skills"][0]["Is_Primary_Skill"] == "Yes"
    assert result["records"]["position"]["Approved_Position"] == "Yes"
    assert result["records"]["position"]["Reporting_Position_ID"] == "P-0"
    assert result["records"]["position"]["Annual_Salary_Budget"] == 1500000
    assert result["records"]["position"]["Vacancy_Start_Date"] == "2025-12-01"
    assert result["records"]["position_skill_requirements"][0]["Skill_ID"] == "S-1"
    assert result["records"]["position_skill_requirements"][0]["Mandatory_Flag"] == "Yes"
    assert result["records"]["position_requirements"]["Required_Skills_Summary"] == "Python"
    assert result["data_quality"]["runtime_source"] == "knowledge_graph"


def test_step9_employee_name_search_preserves_clarification_contract():
    semantic, _ = _services()
    service = GraphEmployeeRecordService(semantic, tenant_id="ORG-1")
    result = service.search(employee_name="Ali Khan")
    assert result["status"] == "found"
    assert result["match_method"] == "exact_name"


def test_step9_attrition_graph_features_match_legacy_model_scoring():
    semantic, features = _services()
    graph_service = GraphAttritionPredictionService(
        model_path=MODEL_PATH,
        feature_service=features,
        tenant_id="ORG-1",
    )
    graph_result = graph_service.predict_employee("E-1")

    legacy_record = GraphEmployeeRecordService(semantic, tenant_id="ORG-1").get_by_employee_id("E-1")
    legacy_result = AttritionPredictor(MODEL_PATH).predict(legacy_record)
    assert graph_result == legacy_result
    assert graph_result["attrition"] in {"Yes", "No"}


def test_step9_attrition_uses_exact_saved_model_feature_order():
    semantic, features = _services()
    service = GraphAttritionPredictionService(
        model_path=MODEL_PATH,
        feature_service=features,
        tenant_id="ORG-1",
    )
    envelope = features.attrition_model_input(tenant_id="ORG-1", employee_id="E-1")
    assert envelope.feature_order == service.predictor.feature_order
    assert len(envelope.feature_order) == 14


def test_step9_graph_first_manager_swaps_only_compatible_public_tools():
    semantic, features = _services()
    legacy_employee = _FakeTool({"status": "legacy"})
    legacy_attrition = _FakeTool({"attrition": "No", "top_reasons": []})
    runtime = Step9RuntimeManager(
        config=Step9RuntimeConfig(
            mode=RuntimeMode.GRAPH_FIRST,
            tenant_id="ORG-1",
            allow_legacy_fallback=True,
            verify_graph_connectivity=False,
        ),
        model_path=MODEL_PATH,
        legacy_employee_search_tool=legacy_employee,
        legacy_attrition_prediction_tool=legacy_attrition,
        semantic_service=semantic,
        feature_service=features,
    )
    assert runtime.graph_available is True
    assert runtime.employee_search_tool is not legacy_employee
    assert runtime.attrition_prediction_tool is not legacy_attrition
    status = runtime.status()
    assert status.ui_api_contract_preserved is True
    assert status.services[0].active_source == "knowledge_graph"


def test_step9_legacy_mode_is_non_breaking():
    legacy_employee = _FakeTool({"status": "legacy"})
    legacy_attrition = _FakeTool({"attrition": "No", "top_reasons": []})
    runtime = Step9RuntimeManager(
        config=Step9RuntimeConfig(mode=RuntimeMode.LEGACY, tenant_id="ORG-1"),
        model_path=MODEL_PATH,
        legacy_employee_search_tool=legacy_employee,
        legacy_attrition_prediction_tool=legacy_attrition,
    )
    assert runtime.employee_search_tool is legacy_employee
    assert runtime.attrition_prediction_tool is legacy_attrition
    assert runtime.status().graph_available is False


def test_step9_management_router_exposes_runtime_status_for_existing_ui():
    semantic, features = _services()
    runtime = Step9RuntimeManager(
        config=Step9RuntimeConfig(
            mode=RuntimeMode.GRAPH_FIRST,
            tenant_id="ORG-1",
            verify_graph_connectivity=False,
        ),
        model_path=MODEL_PATH,
        legacy_employee_search_tool=_FakeTool({"status": "legacy"}),
        legacy_attrition_prediction_tool=_FakeTool({"attrition": "No"}),
        semantic_service=semantic,
        feature_service=features,
    )
    app = FastAPI()
    app.include_router(create_step9_runtime_router(runtime))
    client = TestClient(app)
    payload = client.get("/runtime/step9/status").json()
    assert payload["step"] == 9
    assert payload["mode"] == "graph_first"
    assert payload["graph_available"] is True
    assert any(item["service"] == "attrition_prediction" for item in payload["services"])


def test_step9_known_source_gaps_are_explicit_not_silently_guessed():
    semantic, features = _services()
    runtime = Step9RuntimeManager(
        config=Step9RuntimeConfig(
            mode=RuntimeMode.GRAPH_FIRST,
            tenant_id="ORG-1",
            verify_graph_connectivity=False,
        ),
        model_path=MODEL_PATH,
        legacy_employee_search_tool=_FakeTool({"status": "legacy"}),
        legacy_attrition_prediction_tool=_FakeTool({"attrition": "No"}),
        semantic_service=semantic,
        feature_service=features,
    )
    by_service = {item.service: item for item in runtime.status().services}
    assert by_service["employee_performance"].state.value == "hybrid"
    assert any("empty" in note.lower() for note in by_service["employee_performance"].notes)
    assert by_service["scenario_simulation"].state.value == "hybrid"
    assert any("Data/Simulation" in note for note in by_service["scenario_simulation"].notes)
