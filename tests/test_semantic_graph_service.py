from __future__ import annotations

from datetime import datetime, timezone

import pytest

from graph.memory_repository import InMemoryGraphRepository
from graph.service import GRAPH_MODEL_SERVICE
from semantic.service import SemanticDataIntegrityError, SemanticHRService


def _node(
    repo,
    *,
    tenant="ORG-1",
    entity_type,
    properties,
    key,
    source_object=None,
):
    node = GRAPH_MODEL_SERVICE.create_node(
        tenant_id=tenant,
        entity_type=entity_type,
        properties=properties,
        source_system="test",
        source_object=source_object or entity_type.lower(),
        source_record_key=key,
        mapping_version="test-step5",
    )
    repo.upsert_node(node)
    return node


def _edge(repo, source, relation, target, *, tenant="ORG-1", key="edge"):
    edge = GRAPH_MODEL_SERVICE.create_relationship(
        tenant_id=tenant,
        relation_type=relation,
        source_node=source,
        target_node=target,
        source_system="test",
        source_object="relationship",
        source_record_key=key,
        mapping_version="test-step5",
    )
    repo.upsert_relationship(edge)
    return edge


def _seed_employee_context():
    repo = InMemoryGraphRepository()
    employee = _node(
        repo,
        entity_type="Employee",
        properties={"employeeId": "E-1", "name": "Ali"},
        key="E-1",
    )
    manager = _node(
        repo,
        entity_type="Employee",
        properties={"employeeId": "E-9", "name": "Sara"},
        key="E-9",
    )
    employment = _node(
        repo,
        entity_type="Employment",
        properties={"employeeStatus": "Active", "dataAsOfDate": "2026-09-01"},
        key="E-1|employment",
    )
    assignment = _node(
        repo,
        entity_type="Assignment",
        properties={
            "assignmentId": "A-1",
            "status": "Current",
            "startDate": "2025-01-01",
        },
        key="A-1",
    )
    department = _node(
        repo,
        entity_type="Department",
        properties={"departmentId": "D-1", "name": "AI"},
        key="D-1",
    )
    position = _node(
        repo,
        entity_type="Position",
        properties={"positionId": "P-1", "title": "ML Engineer"},
        key="P-1",
    )
    compensation_old = _node(
        repo,
        entity_type="CompensationRecord",
        properties={"monthlyAmount": 100000, "currency": "PKR"},
        key="E-1|comp-old",
    ).model_copy(update={"valid_from": datetime(2026, 1, 1, tzinfo=timezone.utc)})
    repo.upsert_node(compensation_old)
    compensation_new = _node(
        repo,
        entity_type="CompensationRecord",
        properties={"monthlyAmount": 120000, "currency": "PKR"},
        key="E-1|comp-new",
    ).model_copy(update={"valid_from": datetime(2026, 8, 1, tzinfo=timezone.utc)})
    repo.upsert_node(compensation_new)
    performance_old = _node(
        repo,
        entity_type="PerformanceRecord",
        properties={"assessmentPeriod": "2026-06", "performanceScore": 72},
        key="E-1|2026-06",
    )
    performance_new = _node(
        repo,
        entity_type="PerformanceRecord",
        properties={"assessmentPeriod": "2026-08", "performanceScore": 84},
        key="E-1|2026-08",
    )
    skill_assessment = _node(
        repo,
        entity_type="EmployeeSkill",
        properties={"skillScore": 88, "dataAsOfDate": "2026-08-01"},
        key="E-1|S-1",
    )
    skill = _node(
        repo,
        entity_type="Skill",
        properties={"skillId": "S-1", "name": "Python"},
        key="S-1",
    )

    _edge(repo, employee, "REPORTS_TO", manager, key="reports")
    _edge(repo, employee, "HAS_EMPLOYMENT", employment, key="employment")
    _edge(repo, employee, "HAS_ASSIGNMENT", assignment, key="assignment")
    _edge(repo, assignment, "IN_DEPARTMENT", department, key="department")
    _edge(repo, assignment, "TO_POSITION", position, key="position")
    _edge(repo, employee, "HAS_COMPENSATION", compensation_old, key="comp-old")
    _edge(repo, employee, "HAS_COMPENSATION", compensation_new, key="comp-new")
    _edge(repo, employee, "HAS_PERFORMANCE_RECORD", performance_old, key="perf-old")
    _edge(repo, employee, "HAS_PERFORMANCE_RECORD", performance_new, key="perf-new")
    _edge(repo, employee, "HAS_SKILL", skill_assessment, key="skill-assessment")
    _edge(repo, skill_assessment, "OF_SKILL", skill, key="canonical-skill")
    return repo


def test_repository_step5_reads_are_tenant_scoped():
    repo = InMemoryGraphRepository()
    _node(
        repo,
        tenant="ORG-1",
        entity_type="Employee",
        properties={"employeeId": "E-1", "name": "Ali"},
        key="E-1",
    )
    _node(
        repo,
        tenant="ORG-2",
        entity_type="Employee",
        properties={"employeeId": "E-1", "name": "Different Ali"},
        key="E-1",
    )
    assert len(repo.find_nodes(tenant_id="ORG-1", entity_type="Employee")) == 1
    assert len(repo.find_nodes(tenant_id="ORG-2", entity_type="Employee")) == 1


def test_semantic_employee_lookup_uses_business_id_not_graph_id():
    service = SemanticHRService(_seed_employee_context())
    employee = service.get_employee(tenant_id="ORG-1", employee_id="E-1")
    assert employee is not None
    assert employee.entity_type == "Employee"
    assert employee.properties["name"] == "Ali"


def test_employee_context_resolves_assignment_department_position_manager():
    service = SemanticHRService(_seed_employee_context())
    context = service.get_employee_context(tenant_id="ORG-1", employee_id="E-1")
    assert context is not None
    assert context.current_assignment.properties["assignmentId"] == "A-1"
    assert context.department.properties["departmentId"] == "D-1"
    assert context.position.properties["positionId"] == "P-1"
    assert context.manager.properties["employeeId"] == "E-9"


def test_semantic_latest_record_selection_uses_confirmed_temporal_fields_or_validity():
    service = SemanticHRService(_seed_employee_context())
    performance = service.get_performance(tenant_id="ORG-1", employee_id="E-1")
    compensation = service.get_compensation(tenant_id="ORG-1", employee_id="E-1")
    assert performance.properties["performanceScore"] == 84
    assert compensation.properties["monthlyAmount"] == 120000


def test_skills_resolve_employee_skill_to_canonical_skill():
    service = SemanticHRService(_seed_employee_context())
    skills = service.get_skills(tenant_id="ORG-1", employee_id="E-1")
    assert len(skills) == 1
    assert skills[0].assessment.properties["skillScore"] == 88
    assert skills[0].skill.properties["name"] == "Python"


def test_reporting_chain_returns_manager_chain():
    repo = _seed_employee_context()
    top = _node(
        repo,
        entity_type="Employee",
        properties={"employeeId": "E-10", "name": "Director"},
        key="E-10",
    )
    manager = repo.find_nodes(
        tenant_id="ORG-1", entity_type="Employee", property_filters={"employeeId": "E-9"}
    )[0]
    _edge(repo, manager, "REPORTS_TO", top, key="manager-reports")
    service = SemanticHRService(repo)
    chain = service.get_reporting_chain(tenant_id="ORG-1", employee_id="E-1")
    assert [item.properties["employeeId"] for item in chain] == ["E-9", "E-10"]


def test_reporting_cycle_is_rejected_by_semantic_layer():
    repo = _seed_employee_context()
    employee = repo.find_nodes(
        tenant_id="ORG-1", entity_type="Employee", property_filters={"employeeId": "E-1"}
    )[0]
    manager = repo.find_nodes(
        tenant_id="ORG-1", entity_type="Employee", property_filters={"employeeId": "E-9"}
    )[0]
    _edge(repo, manager, "REPORTS_TO", employee, key="cycle")
    service = SemanticHRService(repo)
    with pytest.raises(SemanticDataIntegrityError, match="cycle"):
        service.get_reporting_chain(tenant_id="ORG-1", employee_id="E-1")


def test_missing_employee_returns_none_without_guessing():
    service = SemanticHRService(_seed_employee_context())
    assert service.get_employee(tenant_id="ORG-1", employee_id="DOES-NOT-EXIST") is None
    assert service.get_employee_context(tenant_id="ORG-1", employee_id="DOES-NOT-EXIST") is None


def test_semantic_health_uses_repository_counts():
    service = SemanticHRService(_seed_employee_context())
    health = service.health("ORG-1")
    assert health["step"] == 5
    assert health["repository"] == "InMemoryGraphRepository"
    assert health["node_count"] > 0
    assert health["relationship_count"] > 0


def test_multiple_undated_records_are_not_guessed_as_latest():
    repo = InMemoryGraphRepository()
    employee = _node(
        repo, entity_type="Employee", properties={"employeeId": "E-X"}, key="E-X"
    )
    first = _node(
        repo,
        entity_type="CompensationRecord",
        properties={"monthlyAmount": 100000},
        key="E-X|1",
    )
    second = _node(
        repo,
        entity_type="CompensationRecord",
        properties={"monthlyAmount": 110000},
        key="E-X|2",
    )
    _edge(repo, employee, "HAS_COMPENSATION", first, key="c1")
    _edge(repo, employee, "HAS_COMPENSATION", second, key="c2")
    service = SemanticHRService(repo)
    with pytest.raises(SemanticDataIntegrityError, match="Cannot select a latest CompensationRecord"):
        service.get_compensation(tenant_id="ORG-1", employee_id="E-X")
