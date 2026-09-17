"""Semantic / Graph Service Layer for the HR platform (roadmap Step 5).

This module is intentionally read-oriented. It hides graph IDs, Neo4j/Cypher,
and ontology traversal details from future AI-service adapters. It does not
perform source ingestion (Step 6/7) and does not refactor current AI services
(Step 9).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Iterable

from graph.neo4j_repository import Neo4jGraphRepository
from graph.repository import GraphRepository
from graph.schema import DEFAULT_GRAPH_SCHEMA, GraphSchema

from .models import EmployeeContext, EmployeeSkillContext, SemanticRecord


class SemanticDataIntegrityError(RuntimeError):
    """Raised when graph contents violate a uniqueness expectation."""


_TEMPORAL_PROPERTIES: dict[str, tuple[str, ...]] = {
    "Employment": ("dataAsOfDate", "hireDate"),
    "Assignment": ("dataAsOfDate", "startDate"),
    "PerformanceRecord": ("dataAsOfDate", "assessmentPeriod"),
    "PerformanceSummary": ("dataAsOfDate", "latestPerformanceMonth"),
    "AttendanceRecord": ("dataAsOfDate", "attendancePeriod"),
    "EngagementRecord": ("dataAsOfDate",),
    "EmployeeSkill": ("dataAsOfDate",),
    "LearningRecord": ("dataAsOfDate", "completionDate"),
    "CareerMovement": ("effectiveDate",),
}


def _as_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    candidates = [text, text + "-01" if len(text) == 7 else text]
    for candidate in candidates:
        try:
            parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            try:
                parsed_date = date.fromisoformat(candidate)
                return datetime(
                    parsed_date.year, parsed_date.month, parsed_date.day, tzinfo=timezone.utc
                )
            except ValueError:
                continue
    return None


def _semantic_time(node) -> datetime | None:
    """Return confirmed business/validity time, never ingestion/update time."""
    for property_name in _TEMPORAL_PROPERTIES.get(node.entity_type, ()):
        parsed = _as_datetime(node.properties.get(property_name))
        if parsed is not None:
            return parsed
    return _as_datetime(node.valid_from)


def _node_rank(node) -> tuple[datetime, str]:
    return (
        _semantic_time(node) or datetime.min.replace(tzinfo=timezone.utc),
        node.graph_id,
    )


def _latest(nodes: Iterable) -> Any | None:
    values = list(nodes)
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    dated = [(value, _semantic_time(value)) for value in values]
    dated = [(value, when) for value, when in dated if when is not None]
    if not dated:
        entity_type = values[0].entity_type
        raise SemanticDataIntegrityError(
            f"Cannot select a latest {entity_type} from multiple records without "
            "a confirmed temporal property or kg_valid_from"
        )
    return max(dated, key=lambda item: (item[1], item[0].graph_id))[0]


class SemanticHRService:
    """Canonical HR read API over any GraphRepository implementation."""

    def __init__(
        self,
        repository: GraphRepository,
        *,
        schema: GraphSchema = DEFAULT_GRAPH_SCHEMA,
    ) -> None:
        self.repository = repository
        self.schema = schema

    @classmethod
    def from_env(cls, *, verify_connectivity: bool = True) -> "SemanticHRService":
        repository = Neo4jGraphRepository.from_env()
        if verify_connectivity:
            repository.verify_connectivity()
        return cls(repository)

    def close(self) -> None:
        close = getattr(self.repository, "close", None)
        if callable(close):
            close()

    def health(self, tenant_id: str | None = None) -> dict[str, Any]:
        return {
            "step": 5,
            "name": "Semantic / Graph Service Layer",
            "repository": type(self.repository).__name__,
            "tenant_id": tenant_id,
            "node_count": self.repository.count_nodes(tenant_id),
            "relationship_count": self.repository.count_relationships(tenant_id),
            "ontology_version": self.schema.ontology_version,
        }

    def get_entity_by_business_id(
        self,
        *,
        tenant_id: str,
        entity_type: str,
        business_id: str,
    ) -> SemanticRecord | None:
        rule = self.schema.identity_rule(entity_type)
        if rule.get("mode") != "ontology_property" or not rule.get("property"):
            raise ValueError(
                f"{entity_type} has no confirmed ontology business-ID property; "
                "query it by semantic filters instead"
            )
        nodes = self.repository.find_nodes(
            tenant_id=tenant_id,
            entity_type=entity_type,
            property_filters={str(rule["property"]): str(business_id)},
            limit=2,
        )
        if len(nodes) > 1:
            raise SemanticDataIntegrityError(
                f"Multiple {entity_type} nodes found for business ID {business_id!r} "
                f"within tenant {tenant_id!r}"
            )
        return SemanticRecord.from_node(nodes[0]) if nodes else None

    def find_entities(
        self,
        *,
        tenant_id: str,
        entity_type: str,
        filters: dict[str, Any] | None = None,
        limit: int = 100,
    ) -> list[SemanticRecord]:
        self.schema.ontology_registry.get_entity(entity_type)
        nodes = self.repository.find_nodes(
            tenant_id=tenant_id,
            entity_type=entity_type,
            property_filters=filters,
            limit=limit,
        )
        return [SemanticRecord.from_node(node) for node in nodes]

    def get_employee(self, *, tenant_id: str, employee_id: str) -> SemanticRecord | None:
        return self.get_entity_by_business_id(
            tenant_id=tenant_id,
            entity_type="Employee",
            business_id=employee_id,
        )

    def find_employees_by_name(
        self, *, tenant_id: str, name: str, limit: int = 20
    ) -> list[SemanticRecord]:
        return self.find_entities(
            tenant_id=tenant_id,
            entity_type="Employee",
            filters={"name": name},
            limit=limit,
        )

    def _employee_node(self, *, tenant_id: str, employee_id: str):
        nodes = self.repository.find_nodes(
            tenant_id=tenant_id,
            entity_type="Employee",
            property_filters={"employeeId": employee_id},
            limit=2,
        )
        if len(nodes) > 1:
            raise SemanticDataIntegrityError(
                f"Multiple Employee nodes found for employeeId {employee_id!r} "
                f"within tenant {tenant_id!r}"
            )
        return nodes[0] if nodes else None

    def _employee_related(
        self,
        *,
        tenant_id: str,
        employee_id: str,
        relation_type: str,
        entity_type: str,
        limit: int = 100,
    ) -> list:
        employee = self._employee_node(tenant_id=tenant_id, employee_id=employee_id)
        if employee is None:
            return []
        return self.repository.related_nodes(
            tenant_id=tenant_id,
            graph_id=employee.graph_id,
            relation_type=relation_type,
            direction="out",
            entity_type=entity_type,
            limit=limit,
        )

    def _latest_employee_related(
        self,
        *,
        tenant_id: str,
        employee_id: str,
        relation_type: str,
        entity_type: str,
    ) -> SemanticRecord | None:
        node = _latest(
            self._employee_related(
                tenant_id=tenant_id,
                employee_id=employee_id,
                relation_type=relation_type,
                entity_type=entity_type,
            )
        )
        return SemanticRecord.from_node(node) if node else None

    def get_employment(self, *, tenant_id: str, employee_id: str) -> SemanticRecord | None:
        return self._latest_employee_related(
            tenant_id=tenant_id,
            employee_id=employee_id,
            relation_type="HAS_EMPLOYMENT",
            entity_type="Employment",
        )

    def get_employment_history(
        self, *, tenant_id: str, employee_id: str
    ) -> list[SemanticRecord]:
        nodes = self._employee_related(
            tenant_id=tenant_id,
            employee_id=employee_id,
            relation_type="HAS_EMPLOYMENT",
            entity_type="Employment",
        )
        return [SemanticRecord.from_node(node) for node in sorted(nodes, key=_node_rank, reverse=True)]

    def get_assignments(self, *, tenant_id: str, employee_id: str) -> list[SemanticRecord]:
        nodes = self._employee_related(
            tenant_id=tenant_id,
            employee_id=employee_id,
            relation_type="HAS_ASSIGNMENT",
            entity_type="Assignment",
        )
        return [SemanticRecord.from_node(node) for node in sorted(nodes, key=_node_rank, reverse=True)]

    def _current_assignment_node(self, *, tenant_id: str, employee_id: str):
        nodes = self._employee_related(
            tenant_id=tenant_id,
            employee_id=employee_id,
            relation_type="HAS_ASSIGNMENT",
            entity_type="Assignment",
        )
        current = [
            node
            for node in nodes
            if str(node.properties.get("status", "")).strip().lower() == "current"
        ]
        return _latest(current or nodes)

    def get_current_assignment(
        self, *, tenant_id: str, employee_id: str
    ) -> SemanticRecord | None:
        node = self._current_assignment_node(tenant_id=tenant_id, employee_id=employee_id)
        return SemanticRecord.from_node(node) if node else None

    def _assignment_related(
        self,
        *,
        tenant_id: str,
        employee_id: str,
        relation_type: str,
        entity_type: str,
    ) -> SemanticRecord | None:
        assignment = self._current_assignment_node(tenant_id=tenant_id, employee_id=employee_id)
        if assignment is None:
            return None
        nodes = self.repository.related_nodes(
            tenant_id=tenant_id,
            graph_id=assignment.graph_id,
            relation_type=relation_type,
            direction="out",
            entity_type=entity_type,
            limit=2,
        )
        if len(nodes) > 1:
            raise SemanticDataIntegrityError(
                f"Current assignment has multiple {relation_type} targets for tenant {tenant_id!r}"
            )
        return SemanticRecord.from_node(nodes[0]) if nodes else None

    def get_department(self, *, tenant_id: str, employee_id: str) -> SemanticRecord | None:
        return self._assignment_related(
            tenant_id=tenant_id,
            employee_id=employee_id,
            relation_type="IN_DEPARTMENT",
            entity_type="Department",
        )

    def get_position(self, *, tenant_id: str, employee_id: str) -> SemanticRecord | None:
        return self._assignment_related(
            tenant_id=tenant_id,
            employee_id=employee_id,
            relation_type="TO_POSITION",
            entity_type="Position",
        )

    def get_manager(self, *, tenant_id: str, employee_id: str) -> SemanticRecord | None:
        employee = self._employee_node(tenant_id=tenant_id, employee_id=employee_id)
        if employee is None:
            return None
        nodes = self.repository.related_nodes(
            tenant_id=tenant_id,
            graph_id=employee.graph_id,
            relation_type="REPORTS_TO",
            direction="out",
            entity_type="Employee",
            limit=2,
        )
        if len(nodes) > 1:
            raise SemanticDataIntegrityError(
                f"Employee {employee_id!r} has multiple REPORTS_TO targets in tenant {tenant_id!r}"
            )
        return SemanticRecord.from_node(nodes[0]) if nodes else None

    def get_reporting_chain(
        self, *, tenant_id: str, employee_id: str, max_depth: int = 20
    ) -> list[SemanticRecord]:
        if max_depth < 1:
            raise ValueError("max_depth must be >= 1")
        current = self._employee_node(tenant_id=tenant_id, employee_id=employee_id)
        if current is None:
            return []
        seen = {current.graph_id}
        result: list[SemanticRecord] = []
        for _ in range(max_depth):
            managers = self.repository.related_nodes(
                tenant_id=tenant_id,
                graph_id=current.graph_id,
                relation_type="REPORTS_TO",
                direction="out",
                entity_type="Employee",
                limit=2,
            )
            if not managers:
                break
            if len(managers) > 1:
                raise SemanticDataIntegrityError(
                    f"Employee node {current.graph_id!r} has multiple REPORTS_TO targets"
                )
            manager = managers[0]
            if manager.graph_id in seen:
                raise SemanticDataIntegrityError("Reporting chain contains a cycle")
            seen.add(manager.graph_id)
            result.append(SemanticRecord.from_node(manager))
            current = manager
        return result

    def get_compensation(self, *, tenant_id: str, employee_id: str) -> SemanticRecord | None:
        return self._latest_employee_related(
            tenant_id=tenant_id,
            employee_id=employee_id,
            relation_type="HAS_COMPENSATION",
            entity_type="CompensationRecord",
        )

    def get_performance(self, *, tenant_id: str, employee_id: str) -> SemanticRecord | None:
        return self._latest_employee_related(
            tenant_id=tenant_id,
            employee_id=employee_id,
            relation_type="HAS_PERFORMANCE_RECORD",
            entity_type="PerformanceRecord",
        )

    def get_performance_summary(
        self, *, tenant_id: str, employee_id: str
    ) -> SemanticRecord | None:
        return self._latest_employee_related(
            tenant_id=tenant_id,
            employee_id=employee_id,
            relation_type="HAS_PERFORMANCE_SUMMARY",
            entity_type="PerformanceSummary",
        )

    def get_attendance(self, *, tenant_id: str, employee_id: str) -> SemanticRecord | None:
        return self._latest_employee_related(
            tenant_id=tenant_id,
            employee_id=employee_id,
            relation_type="HAS_ATTENDANCE_RECORD",
            entity_type="AttendanceRecord",
        )

    def get_engagement(self, *, tenant_id: str, employee_id: str) -> SemanticRecord | None:
        return self._latest_employee_related(
            tenant_id=tenant_id,
            employee_id=employee_id,
            relation_type="HAS_ENGAGEMENT_RECORD",
            entity_type="EngagementRecord",
        )

    def get_experience(self, *, tenant_id: str, employee_id: str) -> SemanticRecord | None:
        return self._latest_employee_related(
            tenant_id=tenant_id,
            employee_id=employee_id,
            relation_type="HAS_EXPERIENCE_PROFILE",
            entity_type="ExperienceProfile",
        )

    def get_succession_readiness(
        self, *, tenant_id: str, employee_id: str
    ) -> SemanticRecord | None:
        return self._latest_employee_related(
            tenant_id=tenant_id,
            employee_id=employee_id,
            relation_type="HAS_SUCCESSION_READINESS",
            entity_type="SuccessionReadiness",
        )

    def get_skills(
        self, *, tenant_id: str, employee_id: str
    ) -> list[EmployeeSkillContext]:
        assessments = self._employee_related(
            tenant_id=tenant_id,
            employee_id=employee_id,
            relation_type="HAS_SKILL",
            entity_type="EmployeeSkill",
        )
        result: list[EmployeeSkillContext] = []
        for assessment in sorted(assessments, key=_node_rank, reverse=True):
            skills = self.repository.related_nodes(
                tenant_id=tenant_id,
                graph_id=assessment.graph_id,
                relation_type="OF_SKILL",
                direction="out",
                entity_type="Skill",
                limit=2,
            )
            if len(skills) > 1:
                raise SemanticDataIntegrityError(
                    f"EmployeeSkill {assessment.graph_id!r} references multiple canonical Skill nodes"
                )
            result.append(
                EmployeeSkillContext(
                    assessment=SemanticRecord.from_node(assessment),
                    skill=SemanticRecord.from_node(skills[0]) if skills else None,
                )
            )
        return result

    def _history(
        self,
        *,
        tenant_id: str,
        employee_id: str,
        relation_type: str,
        entity_type: str,
    ) -> list[SemanticRecord]:
        nodes = self._employee_related(
            tenant_id=tenant_id,
            employee_id=employee_id,
            relation_type=relation_type,
            entity_type=entity_type,
        )
        return [SemanticRecord.from_node(node) for node in sorted(nodes, key=_node_rank, reverse=True)]

    def get_employee_context(
        self, *, tenant_id: str, employee_id: str
    ) -> EmployeeContext | None:
        employee_node = self._employee_node(tenant_id=tenant_id, employee_id=employee_id)
        if employee_node is None:
            return None

        employment_history = self._history(
            tenant_id=tenant_id,
            employee_id=employee_id,
            relation_type="HAS_EMPLOYMENT",
            entity_type="Employment",
        )
        assignment_history = self.get_assignments(
            tenant_id=tenant_id, employee_id=employee_id
        )
        compensation_history = self._history(
            tenant_id=tenant_id,
            employee_id=employee_id,
            relation_type="HAS_COMPENSATION",
            entity_type="CompensationRecord",
        )
        performance_history = self._history(
            tenant_id=tenant_id,
            employee_id=employee_id,
            relation_type="HAS_PERFORMANCE_RECORD",
            entity_type="PerformanceRecord",
        )
        performance_summary_history = self._history(
            tenant_id=tenant_id,
            employee_id=employee_id,
            relation_type="HAS_PERFORMANCE_SUMMARY",
            entity_type="PerformanceSummary",
        )
        attendance_history = self._history(
            tenant_id=tenant_id,
            employee_id=employee_id,
            relation_type="HAS_ATTENDANCE_RECORD",
            entity_type="AttendanceRecord",
        )
        engagement_history = self._history(
            tenant_id=tenant_id,
            employee_id=employee_id,
            relation_type="HAS_ENGAGEMENT_RECORD",
            entity_type="EngagementRecord",
        )
        experience_history = self._history(
            tenant_id=tenant_id,
            employee_id=employee_id,
            relation_type="HAS_EXPERIENCE_PROFILE",
            entity_type="ExperienceProfile",
        )
        learning_history = self._history(
            tenant_id=tenant_id,
            employee_id=employee_id,
            relation_type="HAS_LEARNING_RECORD",
            entity_type="LearningRecord",
        )
        career_movements = self._history(
            tenant_id=tenant_id,
            employee_id=employee_id,
            relation_type="HAS_CAREER_MOVEMENT",
            entity_type="CareerMovement",
        )
        succession_history = self._history(
            tenant_id=tenant_id,
            employee_id=employee_id,
            relation_type="HAS_SUCCESSION_READINESS",
            entity_type="SuccessionReadiness",
        )

        return EmployeeContext(
            tenant_id=tenant_id,
            employee=SemanticRecord.from_node(employee_node),
            employment=employment_history[0] if employment_history else None,
            current_assignment=self.get_current_assignment(
                tenant_id=tenant_id, employee_id=employee_id
            ),
            department=self.get_department(tenant_id=tenant_id, employee_id=employee_id),
            position=self.get_position(tenant_id=tenant_id, employee_id=employee_id),
            manager=self.get_manager(tenant_id=tenant_id, employee_id=employee_id),
            compensation=compensation_history[0] if compensation_history else None,
            performance=performance_history[0] if performance_history else None,
            performance_summary=(
                performance_summary_history[0] if performance_summary_history else None
            ),
            attendance=attendance_history[0] if attendance_history else None,
            engagement=engagement_history[0] if engagement_history else None,
            experience=experience_history[0] if experience_history else None,
            succession_readiness=(succession_history[0] if succession_history else None),
            skills=self.get_skills(tenant_id=tenant_id, employee_id=employee_id),
            employment_history=employment_history,
            assignment_history=assignment_history,
            compensation_history=compensation_history,
            performance_history=performance_history,
            performance_summary_history=performance_summary_history,
            attendance_history=attendance_history,
            engagement_history=engagement_history,
            experience_history=experience_history,
            learning_history=learning_history,
            career_movements=career_movements,
            succession_readiness_history=succession_history,
        )
