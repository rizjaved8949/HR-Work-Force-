"""Service-contract coverage for a proposed/approved mapping plan."""
from __future__ import annotations

from typing import Any

from ontology.registry import DEFAULT_REGISTRY, OntologyRegistry

from .models import MappingPlan


def _collect_ontology_paths(value: Any, *, parent_key: str | None = None) -> set[str]:
    result: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "ontology_path" and isinstance(item, str):
                result.add(item)
            elif key == "ontology_identity_paths" and isinstance(item, list):
                result.update(str(x) for x in item if isinstance(x, str) and "." in x)
            else:
                result.update(_collect_ontology_paths(item, parent_key=key))
    elif isinstance(value, list):
        for item in value:
            result.update(_collect_ontology_paths(item, parent_key=parent_key))
    return result


class ServiceCoverageAnalyzer:
    def __init__(self, ontology: OntologyRegistry = DEFAULT_REGISTRY) -> None:
        self.ontology = ontology

    def required_paths(self, service_name: str) -> set[str]:
        contract = self.ontology.get_service_contract(service_name)
        return {
            path
            for path in _collect_ontology_paths(contract)
            if self.ontology.ontology_path_exists(path)
        }

    def report(self, plan: MappingPlan) -> dict[str, Any]:
        available = {item.ontology_path for item in plan.property_mappings}
        services: dict[str, Any] = {}
        for service_name in self.ontology.list_service_contracts():
            required = self.required_paths(service_name)
            if not required:
                continue
            covered = sorted(required & available)
            missing = sorted(required - available)
            services[service_name] = {
                "required_path_count": len(required),
                "covered_path_count": len(covered),
                "coverage_percent": round((len(covered) / len(required)) * 100, 2) if required else 100.0,
                "covered_paths": covered,
                "missing_paths": missing,
                "note": "Coverage is source-plan availability only; Step 8 decides feature derivation/missing-feature behavior.",
            }
        return {
            "mapping_plan_id": plan.plan_id,
            "mapping_status": plan.status,
            "available_ontology_paths": sorted(available),
            "services": services,
        }


DEFAULT_COVERAGE_ANALYZER = ServiceCoverageAnalyzer()
