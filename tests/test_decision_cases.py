from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from decision_cases.data_repository import DecisionCaseDataRepository
from decision_cases.engine import DecisionTriggerEngine
from decision_cases.rule_catalog import DecisionTriggerRuleCatalog
from decision_cases.service import DecisionCaseService
from decision_cases.store import CsvDecisionCaseStore, InMemoryDecisionCaseStore


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "Data"


class FakeAttritionTool:
    """Deterministic test double; production uses the existing CatBoost tool."""

    def invoke(self, payload: dict) -> dict:
        row = payload["employee_record"]["records"]["attrition_features"]
        if row.get("Employee_ID") == "EMP292":
            return {
                "attrition": "Yes",
                "top_reasons": ["Career_Growth_Score", "Salary_vs_Market_pct"],
            }
        return {"attrition": "No", "top_reasons": []}


class FakeSuccessorReadiness:
    def evaluate(self, employee_id: str) -> dict:
        if employee_id == "EMP292":
            return {
                "status": "success",
                "has_ready_now": False,
                "candidate_count": 3,
                "top_candidate": {
                    "employee_id": "EMP123",
                    "employee_name": "Example Candidate",
                    "current_position": "Senior Engineer",
                    "final_score": 82.75,
                    "qualification_status": "Qualified",
                    "readiness": "Ready in 6-12 Months",
                },
            }
        return {
            "status": "success",
            "has_ready_now": True,
            "candidate_count": 1,
            "top_candidate": None,
        }


class _FakeResponse:
    def __init__(self, data):
        self.data = data


class _FakeQuery:
    def __init__(self, rows):
        self.rows = rows
        self.start = 0
        self.end = None

    def select(self, _columns):
        return self

    def range(self, start, end):
        self.start, self.end = start, end
        return self

    def execute(self):
        if self.end is None:
            return _FakeResponse(self.rows)
        return _FakeResponse(self.rows[self.start : self.end + 1])


class _FakeSupabase:
    def __init__(self, tables):
        self.tables = tables

    def table(self, name):
        return _FakeQuery(self.tables[name])


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _service(
    data_dir: Path = DATA,
    *,
    store=None,
) -> DecisionCaseService:
    engine = DecisionTriggerEngine(
        data_repository=DecisionCaseDataRepository(data_dir, source="csv"),
        attrition_prediction_tool=FakeAttritionTool(),
        successor_readiness=FakeSuccessorReadiness(),
    )
    return DecisionCaseService(
        engine=engine,
        store=store or InMemoryDecisionCaseStore(),
        dashboard_limit=5,
    )


def _copy_data(tmp_path: Path) -> Path:
    target = tmp_path / "Data"
    shutil.copytree(DATA, target)
    # Do not let generated case state from the repository fixture influence a
    # new test. Cases must be detected from the copied source data.
    (target / "HR_Decision_Cases.csv").unlink(missing_ok=True)
    return target


def test_rule_catalog_contains_exactly_five_focused_rules() -> None:
    catalog = DecisionTriggerRuleCatalog(DATA / "HR_Decision_Trigger_Rules.csv")
    rules = catalog.all()
    assert len(rules) == 5
    assert {rule.rule_id for rule in rules} == {
        "DTE-001", "DTE-002", "DTE-003", "DTE-004", "DTE-005"
    }
    assert all(rule.enabled for rule in rules)
    assert all(rule.priority in {"Critical", "High"} for rule in rules)


def test_current_dataset_produces_small_high_value_queue() -> None:
    result = _service().evaluate()

    assert result.dashboard_limit == 5
    # DTE-004 is correctly defined but does not currently fire: the supplied
    # vacancy data has no Currently Open position with Critical criticality.
    assert result.detected_case_count == 4
    assert result.dashboard_case_count == 4
    assert [case.rule_id for case in result.cases] == [
        "DTE-001",
        "DTE-003",
        "DTE-005",
        "DTE-002",
    ]
    assert all(case.priority in {"Critical", "High"} for case in result.cases)


def test_cases_change_when_source_data_changes_not_from_hardcoded_rows(tmp_path: Path) -> None:
    data_dir = _copy_data(tmp_path)

    # Remove the one current critical-role declining trend.
    perf_path = data_dir / "Employee_Performance_Summary.csv"
    perf = pd.read_csv(perf_path)
    perf.loc[perf["Employee_ID"] == "EMP277", "Performance_Trend"] = "Stable"
    perf.to_csv(perf_path, index=False)

    result = _service(data_dir).evaluate()
    assert "DTE-002" not in {case.rule_id for case in result.cases}

    # Create a valid DTE-004 input by changing source DATA only. The threshold
    # remains sourced from existing Headcount RULE-004 (60 days).
    vacancy_path = data_dir / "Position_Vacancy_History.csv"
    vacancies = pd.read_csv(vacancy_path)
    target = vacancies["Vacancy_Status"].eq("Currently Open")
    idx = vacancies[target].index[0]
    vacancies.loc[idx, "Position_Criticality"] = "Critical"
    vacancies.loc[idx, "Vacancy_Age_in_Days"] = 61
    vacancies.to_csv(vacancy_path, index=False)

    result = _service(data_dir).evaluate()
    vacancy_case = next(case for case in result.cases if case.rule_id == "DTE-004")
    assert vacancy_case.evidence["vacancy_age_threshold_days"] == 60
    assert vacancy_case.evidence["critical_vacancy_count"] >= 1


def test_evaluation_is_idempotent_and_preserves_hr_status() -> None:
    service = _service()
    first = service.evaluate()
    first_ids = {case.case_key: case.id for case in first.cases}

    retention = next(case for case in first.cases if case.rule_id == "DTE-001")
    updated = service.update_status(retention.id, "Under Review")
    assert updated is not None
    assert updated.status == "Under Review"

    second = service.evaluate()
    second_ids = {case.case_key: case.id for case in second.cases}
    assert first_ids == second_ids

    refreshed = next(case for case in second.cases if case.id == retention.id)
    assert refreshed.status == "Under Review"


def test_engine_does_not_mutate_existing_source_csvs() -> None:
    source_files = [
        DATA / "Employee_Profile.csv",
        DATA / "Employee_Performance_Summary.csv",
        DATA / "Position_Master.csv",
        DATA / "Final_Attrition_Dataset_200_Employees.csv",
        DATA / "Headcount_Exception_Register.csv",
        DATA / "Headcount_Management_Rules.csv",
        DATA / "Position_Vacancy_History.csv",
        DATA / "HR_Decision_Trigger_Rules.csv",
        DATA / "HR_Decision_Data_Source_Map.csv",
    ]
    before = {path.name: _hash(path) for path in source_files}

    _service().evaluate()

    after = {path.name: _hash(path) for path in source_files}
    assert before == after


def test_csv_case_store_is_generated_and_persists_hr_workflow(tmp_path: Path) -> None:
    data_dir = _copy_data(tmp_path)
    case_file = data_dir / "HR_Decision_Cases.csv"
    service = _service(data_dir, store=CsvDecisionCaseStore(case_file))

    first = service.evaluate()
    assert case_file.is_file()
    assert first.dashboard_case_count == 4

    retention = next(case for case in first.cases if case.rule_id == "DTE-001")
    changed = service.update_status(retention.id, "Under Review")
    assert changed is not None

    # New service instance proves state was persisted to CSV, not memory.
    service2 = _service(data_dir, store=CsvDecisionCaseStore(case_file))
    second = service2.evaluate()
    same = next(case for case in second.cases if case.id == retention.id)
    assert same.status == "Under Review"


def test_dashboard_and_llm_query_path_never_exceeds_five() -> None:
    service = _service()
    service.evaluate()

    # Service clamps direct callers as well; FastAPI additionally validates <=5.
    all_current = service.list_cases(limit=50)
    assert all_current.count <= 5

    critical = service.list_cases(priority="Critical")
    assert critical.count == 3
    assert all(case.priority == "Critical" for case in critical.cases)

    employee = service.list_cases(employee_id="EMP292")
    assert employee.count == 1
    assert employee.cases[0].rule_id == "DTE-001"


def test_recurrent_trigger_reopens_after_it_was_inactive() -> None:
    from datetime import timedelta

    service = _service()
    first = service.evaluate()
    retention = next(case for case in first.cases if case.rule_id == "DTE-001")

    resolved = service.update_status(retention.id, "Resolved")
    assert resolved is not None
    assert resolved.status == "Resolved"

    service.store.sync([], first.evaluated_at + timedelta(days=1))
    inactive = service.get_case(retention.id)
    assert inactive is not None
    assert inactive.is_trigger_active is False

    service.evaluate()
    reopened = service.get_case(retention.id)
    assert reopened is not None
    assert reopened.is_trigger_active is True
    assert reopened.status == "Open"
    assert reopened.resolved_at is None


def test_supabase_source_mode_uses_same_repository_interface() -> None:
    original = pd.read_csv(DATA / "Employee_Profile.csv").head(2)
    # Simulate the common Supabase/Postgres migration style where CSV columns
    # such as Employee_ID are stored as lowercase snake_case.
    lowered = original.rename(columns={column: column.casefold() for column in original.columns})
    rows = lowered.to_dict("records")
    fake = _FakeSupabase({"employee_profile": rows})
    repo = DecisionCaseDataRepository(
        DATA,
        source="supabase",
        client_factory=lambda: fake,
        page_size=100,
    )

    frame = repo.read("profiles")
    assert frame.shape[0] == 2
    assert "Employee_ID" in frame.columns
    assert frame.iloc[0]["Employee_ID"] == original.iloc[0]["Employee_ID"]
