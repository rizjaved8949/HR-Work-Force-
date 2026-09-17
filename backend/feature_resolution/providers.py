"""Storage-neutral semantic value providers used by the Step-8 resolver."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from semantic.models import EmployeeContext, SemanticRecord


@dataclass(frozen=True)
class ProvidedValue:
    present: bool
    value: Any = None
    source_reference_ids: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


class SemanticValueProvider(Protocol):
    def get(self, ontology_path: str) -> ProvidedValue: ...


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str) and not value.strip():
        return False
    return True


class MappingValueProvider:
    """Resolve ontology paths from an explicit semantic-value mapping.

    This provider is useful for deterministic/non-employee Step-9 adapters such as
    performance recalculation. Keys must already be ontology paths; raw database
    column names are intentionally not accepted by the resolver itself.
    """

    def __init__(self, values: dict[str, Any], *, source_id: str = "explicit-semantic-values"):
        self.values = dict(values)
        self.source_id = source_id

    def get(self, ontology_path: str) -> ProvidedValue:
        if ontology_path not in self.values:
            return ProvidedValue(present=False)
        value = self.values[ontology_path]
        return ProvidedValue(
            present=_has_value(value),
            value=value,
            source_reference_ids=(self.source_id,),
        )


class EmployeeContextValueProvider:
    """Resolve unambiguous ontology properties from an EmployeeContext.

    Single-record employee-centered entities can be resolved directly. Collection
    entities such as EmployeeSkill are deliberately not guessed here because a
    path alone does not identify which skill assessment should be selected.
    """

    _SINGLE_RECORD_BINDINGS = {
        "Employee": "employee",
        "Employment": "employment",
        "Assignment": "current_assignment",
        "Department": "department",
        "Position": "position",
        "CompensationRecord": "compensation",
        "PerformanceRecord": "performance",
        "PerformanceSummary": "performance_summary",
        "AttendanceRecord": "attendance",
        "EngagementRecord": "engagement",
        "ExperienceProfile": "experience",
        "SuccessionReadiness": "succession_readiness",
    }

    def __init__(self, context: EmployeeContext):
        self.context = context

    @staticmethod
    def _record_value(record: SemanticRecord | None, property_name: str) -> ProvidedValue:
        if record is None:
            return ProvidedValue(present=False)
        value = record.properties.get(property_name)
        return ProvidedValue(
            present=_has_value(value),
            value=value,
            source_reference_ids=(record.reference_id,),
        )

    def get(self, ontology_path: str) -> ProvidedValue:
        if "." not in ontology_path:
            return ProvidedValue(
                present=False,
                notes=(f"Invalid ontology path {ontology_path!r}; expected Entity.property.",),
            )
        entity_name, property_name = ontology_path.split(".", 1)
        attr = self._SINGLE_RECORD_BINDINGS.get(entity_name)
        if attr is not None:
            return self._record_value(getattr(self.context, attr), property_name)

        if entity_name == "CareerMovement":
            # A bare CareerMovement.property path is ambiguous when history contains
            # multiple events; derivation rules inspect the full history explicitly.
            return ProvidedValue(
                present=False,
                notes=("CareerMovement is a history collection; no record was guessed.",),
            )

        if entity_name in {"EmployeeSkill", "Skill", "LearningRecord"}:
            return ProvidedValue(
                present=False,
                notes=(f"{entity_name} is a collection context; selection requires a service-specific rule.",),
            )

        return ProvidedValue(
            present=False,
            notes=(f"No Step-8 employee-context binding is defined for {entity_name}.",),
        )
