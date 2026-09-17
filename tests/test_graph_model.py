from __future__ import annotations

import pytest

from graph.ids import make_node_graph_id
from graph.memory_repository import InMemoryGraphRepository
from graph.service import GRAPH_MODEL_SERVICE


def test_graph_schema_is_valid_and_matches_ontology_counts():
    summary = GRAPH_MODEL_SERVICE.summary()
    report = GRAPH_MODEL_SERVICE.validation_report()
    assert report["valid"] is True
    assert report["error_count"] == 0
    assert summary["node_type_count"] == 39
    assert summary["relationship_schema_count"] == 65


def test_graph_id_is_deterministic_and_tenant_scoped():
    first = make_node_graph_id(
        tenant_id="ORG-1", entity_type="Employee", identity_key="E-100"
    )
    again = make_node_graph_id(
        tenant_id="ORG-1", entity_type="Employee", identity_key="E-100"
    )
    other_tenant = make_node_graph_id(
        tenant_id="ORG-2", entity_type="Employee", identity_key="E-100"
    )
    assert first == again
    assert first != other_tenant


def test_create_and_store_valid_employee_assignment_relationship():
    service = GRAPH_MODEL_SERVICE
    repo = InMemoryGraphRepository()
    employee = service.create_node(
        tenant_id="ORG-1",
        entity_type="Employee",
        properties={"employeeId": "E-1", "name": "Ali"},
        source_system="test",
        source_object="employee",
        source_record_key="E-1",
        mapping_version="test",
    )
    assignment = service.create_node(
        tenant_id="ORG-1",
        entity_type="Assignment",
        properties={"assignmentId": "A-1", "status": "Active"},
        source_system="test",
        source_object="assignment",
        source_record_key="A-1",
        mapping_version="test",
    )
    repo.upsert_node(employee)
    repo.upsert_node(assignment)

    edge = service.create_relationship(
        tenant_id="ORG-1",
        relation_type="HAS_ASSIGNMENT",
        source_node=employee,
        target_node=assignment,
        source_system="test",
        source_object="assignment",
        source_record_key="E-1|A-1",
        mapping_version="test",
    )
    repo.upsert_relationship(edge)
    assert repo.count_nodes("ORG-1") == 2
    assert repo.count_relationships("ORG-1") == 1


def test_invalid_relationship_is_rejected():
    service = GRAPH_MODEL_SERVICE
    employee = service.create_node(
        tenant_id="ORG-1",
        entity_type="Employee",
        properties={"employeeId": "E-1"},
        source_system="test",
        source_object="employee",
        source_record_key="E-1",
    )
    skill = service.create_node(
        tenant_id="ORG-1",
        entity_type="Skill",
        properties={"skillId": "S-1", "name": "Python"},
        source_system="test",
        source_object="skill",
        source_record_key="S-1",
    )
    with pytest.raises(ValueError):
        service.create_relationship(
            tenant_id="ORG-1",
            relation_type="REPORTS_TO",
            source_node=employee,
            target_node=skill,
            source_system="test",
            source_object="bad",
            source_record_key="1",
        )


def test_cross_tenant_relationship_is_rejected():
    service = GRAPH_MODEL_SERVICE
    employee = service.create_node(
        tenant_id="ORG-1",
        entity_type="Employee",
        properties={"employeeId": "E-1"},
        source_system="test",
        source_object="employee",
        source_record_key="E-1",
    )
    department = service.create_node(
        tenant_id="ORG-2",
        entity_type="Department",
        properties={"departmentId": "D-1"},
        source_system="test",
        source_object="department",
        source_record_key="D-1",
    )
    with pytest.raises(ValueError):
        service.create_relationship(
            tenant_id="ORG-1",
            relation_type="BELONGS_TO",
            source_node=employee,
            target_node=department,
            source_system="test",
            source_object="assignment",
            source_record_key="1",
        )


def test_source_record_identity_for_record_without_business_id():
    service = GRAPH_MODEL_SERVICE
    a = service.create_node(
        tenant_id="ORG-1",
        entity_type="PerformanceRecord",
        properties={"assessmentPeriod": "2026-08"},
        source_system="supabase",
        source_object="employee_performance",
        source_record_key="E-1|2026-08",
    )
    b = service.create_node(
        tenant_id="ORG-1",
        entity_type="PerformanceRecord",
        properties={"assessmentPeriod": "2026-08"},
        source_system="supabase",
        source_object="employee_performance",
        source_record_key="E-1|2026-08",
    )
    assert a.graph_id == b.graph_id
