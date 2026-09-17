from __future__ import annotations

import csv
from pathlib import Path

import pytest

from current_graph_load.manifest import DEFAULT_STEP7_MANIFEST
from current_graph_load.plan_builder import DEFAULT_STEP7_PLAN_BUILDER
from current_graph_load.service import CurrentSupabaseGraphLoadService
from current_graph_load.source import SupabaseTableReader
from graph.memory_repository import InMemoryGraphRepository
from ingestion.sources import RecordsSource
from ontology.registry import DEFAULT_REGISTRY


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _records(table: str, rows: list[dict]) -> RecordsSource:
    return RecordsSource(
        rows,
        source_system="supabase",
        source_object=table,
        source_format="supabase",
    )


def test_manifest_is_bound_to_current_verified_mapping_and_known_gaps():
    manifest = DEFAULT_STEP7_MANIFEST.load()
    assert manifest.ontology_version == DEFAULT_REGISTRY.load().version
    assert len(manifest.tables) == 32
    assert any(item["table"] == "headcount_scenario_assumptions" for item in manifest.intentionally_not_loaded)
    assert any("Simulation" in item for item in manifest.known_supabase_snapshot_gaps)


def test_step7_corrects_three_source_grounded_semantic_mismatches():
    leadership = DEFAULT_REGISTRY.get_property("PositionRequirement.leadershipRequired")
    assert leadership.data_type == "string"
    assert set(leadership.enum_values) == {"Yes", "No", "Preferred"}
    assert DEFAULT_REGISTRY.get_property("HeadcountException.currentValue").data_type == "string"
    assert DEFAULT_REGISTRY.get_property("HeadcountException.thresholdValue").data_type == "string"
    spec = DEFAULT_STEP7_MANIFEST.table("organization_master")
    plan = DEFAULT_STEP7_PLAN_BUILDER.build(tenant_id="ORGANIZATION-001", table_spec=spec)
    fiscal = next(item for item in plan.property_mappings if item.source_column == "Fiscal_Year_Start_Month")
    assert fiscal.transform == "month_name_to_number"


def test_small_current_supabase_load_is_two_pass_and_idempotent():
    data = {
        "organization_master": _records("organization_master", [{
            "id": 1,
            "Organization_ID": "ORGANIZATION-001",
            "Organization_Name": "Test Org",
            "Organization_Type": "Test",
            "Country": "Pakistan",
            "Currency": "PKR",
            "Fiscal_Year_Start_Month": "January",
            "Standard_Workweek_Hours": "40",
            "Workforce_Data_As_Of_Date": "2026-08-01",
        }]),
        "business_unit_master": _records("business_unit_master", [{
            "id": 1,
            "Business_Unit_ID": "BU-1",
            "Business_Unit_Name": "Tech",
            "Organization_ID": "ORGANIZATION-001",
            "Business_Unit_Leader_Position_ID": "",
            "Active_Status": "Active",
            "Effective_Start_Date": "2026-01-01",
            "Effective_End_Date": "",
        }]),
    }
    repo = InMemoryGraphRepository()
    service = CurrentSupabaseGraphLoadService(
        repository=repo,
        source_factory=lambda table: data[table],
    )
    tables = {"organization_master", "business_unit_master"}
    preflight = service.preflight(tenant_id="ORGANIZATION-001", tables=tables)
    assert preflight.valid is True
    first = service.load(tenant_id="ORGANIZATION-001", tables=tables)
    assert first.graph_node_count_after == 2
    assert first.graph_relationship_count_after == 1
    second = service.load(tenant_id="ORGANIZATION-001", tables=tables)
    assert second.graph_node_count_after == 2
    assert second.graph_relationship_count_after == 1


def test_reference_only_stubs_preserve_explicit_historical_ids_without_invented_attributes():
    rows = [{
        "id": 1,
        "Movement_ID": "MOVE-1",
        "Employee_ID": "HIST-E-9",
        "Employee_Name": "Historical Name",
        "Movement_Type": "Transfer",
        "Effective_Date": "2025-05-01",
        "From_Department_ID": "D-OLD",
        "From_Department_Name": "Old",
        "To_Department_ID": "D-NEW",
        "To_Department_Name": "New",
        "From_Organizational_Unit_ID": "",
        "To_Organizational_Unit_ID": "",
        "From_Position_ID": "P-OLD",
        "To_Position_ID": "P-NEW",
        "Movement_Reason": "History",
        "Voluntary_Movement": "No",
        "Employee_Record_Availability": "Historical",
        "Source_System": "Legacy",
    }]
    repo = InMemoryGraphRepository()
    service = CurrentSupabaseGraphLoadService(
        repository=repo,
        source_factory=lambda table: _records(table, rows),
    )
    tables = {"workforce_movement_history"}
    report, nodes, _ = service.prepare(tenant_id="ORGANIZATION-001", tables=tables)
    assert report.valid is True
    employee_stubs = [item for item in nodes.values() if item.entity_type == "Employee"]
    assert len(employee_stubs) == 1
    assert employee_stubs[0].properties == {"employeeId": "HIST-E-9"}


def test_wrong_tenant_is_blocked_by_organization_identity_rule():
    source = _records("organization_master", [{
        "id": 1,
        "Organization_ID": "ORGANIZATION-001",
        "Organization_Name": "Test Org",
        "Organization_Type": "Test",
        "Country": "Pakistan",
        "Currency": "PKR",
        "Fiscal_Year_Start_Month": "January",
        "Standard_Workweek_Hours": "40",
        "Workforce_Data_As_Of_Date": "2026-08-01",
    }])
    service = CurrentSupabaseGraphLoadService(
        repository=InMemoryGraphRepository(),
        source_factory=lambda table: source,
    )
    report = service.preflight(tenant_id="WRONG-TENANT", tables={"organization_master"})
    assert report.valid is False
    assert report.error_count >= 1


def test_current_bundled_dataset_preflight_is_clean_without_graph_write():
    by_table = {item.table: item for item in DEFAULT_STEP7_MANIFEST.load().tables}

    def factory(table: str):
        spec = by_table[table]
        path = PROJECT_ROOT / "Data" / spec.matching_csv
        with path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        for index, row in enumerate(rows, start=1):
            row["id"] = index
        return _records(table, rows)

    repo = InMemoryGraphRepository()
    service = CurrentSupabaseGraphLoadService(repository=repo, source_factory=factory)
    report = service.preflight(tenant_id="ORGANIZATION-001")
    assert report.valid is True
    assert report.error_count == 0
    assert report.table_count == 32
    assert report.source_row_count == 93375
    assert report.unique_node_count > 90000
    assert report.unique_relationship_count > 170000
    assert repo.count_nodes() == 0
    assert repo.count_relationships() == 0


class _FakeResponse:
    def __init__(self, data):
        self.data = data


class _FakeQuery:
    def __init__(self, rows):
        self.rows = rows
        self.start = 0
        self.end = 0

    def select(self, _columns):
        return self

    def range(self, start, end):
        self.start, self.end = start, end
        return self

    def execute(self):
        return _FakeResponse(self.rows[self.start:self.end + 1])


class _FakeSupabase:
    def __init__(self, rows):
        self.rows = rows

    def table(self, _name):
        return _FakeQuery(self.rows)


def test_supabase_reader_pages_without_writing():
    reader = SupabaseTableReader(_FakeSupabase([{"id": i} for i in range(5)]), page_size=2)
    assert reader.read_rows("anything") == [{"id": i} for i in range(5)]
