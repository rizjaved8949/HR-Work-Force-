"""Facade for roadmap Step 8 feature resolution.

Existing AI services are intentionally not refactored here. Step 9 will route
those services through this facade after parity tests.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from semantic.service import SemanticHRService

from .adapters import DEFAULT_ATTRITION_ADAPTER, AttritionCatBoostAdapter
from .derivations import DEFAULT_DERIVATIONS, FeatureDerivationRegistry
from .models import FeatureResolutionReport, ModelInputEnvelope, ResolutionStatus
from .providers import EmployeeContextValueProvider, MappingValueProvider, SemanticValueProvider
from .registry import DEFAULT_FEATURE_CONTRACTS, FeatureContractRegistry
from .resolver import FeatureResolver


class FeatureResolutionService:
    def __init__(
        self,
        semantic_service: SemanticHRService,
        *,
        contracts: FeatureContractRegistry = DEFAULT_FEATURE_CONTRACTS,
        resolver: FeatureResolver | None = None,
        derivations: FeatureDerivationRegistry = DEFAULT_DERIVATIONS,
        attrition_adapter: AttritionCatBoostAdapter = DEFAULT_ATTRITION_ADAPTER,
    ) -> None:
        self.semantic_service = semantic_service
        self.contracts = contracts
        self.derivations = derivations
        self.resolver = resolver or FeatureResolver(derivations)
        self.attrition_adapter = attrition_adapter

    @classmethod
    def from_env(cls, *, verify_connectivity: bool = True) -> "FeatureResolutionService":
        return cls(SemanticHRService.from_env(verify_connectivity=verify_connectivity))

    def close(self) -> None:
        self.semantic_service.close()

    def health(self, tenant_id: str | None = None) -> dict[str, Any]:
        semantic_health = self.semantic_service.health(tenant_id)
        return {
            "step": 8,
            "name": "Feature Resolution / Missing Feature Layer",
            "contracts": self.contracts.list_contracts(),
            "rules_version": self.derivations.version,
            "semantic_repository": semantic_health["repository"],
            "tenant_id": tenant_id,
            "graph_node_count": semantic_health["node_count"],
            "graph_relationship_count": semantic_health["relationship_count"],
            "ontology_version": semantic_health["ontology_version"],
        }

    def resolve_from_provider(
        self,
        contract_name: str,
        *,
        provider: SemanticValueProvider,
        tenant_id: str | None = None,
        subject_id: str | None = None,
        as_of_date: date | None = None,
        strict_missing: bool = False,
    ) -> FeatureResolutionReport:
        contract = self.contracts.get(contract_name)
        return self.resolver.resolve(
            contract,
            provider=provider,
            tenant_id=tenant_id,
            subject_id=subject_id,
            as_of_date=as_of_date,
            strict_missing=strict_missing,
        )

    def resolve_semantic_values(
        self,
        contract_name: str,
        values: dict[str, Any],
        *,
        tenant_id: str | None = None,
        subject_id: str | None = None,
        as_of_date: date | None = None,
        strict_missing: bool = False,
    ) -> FeatureResolutionReport:
        """Resolve an explicit ontology-path mapping for non-employee adapters.

        This deliberately accepts ontology paths, not source database columns.
        """
        return self.resolve_from_provider(
            contract_name,
            provider=MappingValueProvider(values),
            tenant_id=tenant_id,
            subject_id=subject_id,
            as_of_date=as_of_date,
            strict_missing=strict_missing,
        )

    def resolve_attrition(
        self,
        *,
        tenant_id: str,
        employee_id: str,
        as_of_date: date | None = None,
        strict_missing: bool = False,
    ) -> FeatureResolutionReport:
        contract = self.contracts.get("attrition")
        context = self.semantic_service.get_employee_context(
            tenant_id=tenant_id,
            employee_id=employee_id,
        )
        if context is None:
            report = self.resolver.resolve(
                contract,
                provider=MappingValueProvider({}, source_id="employee-not-found"),
                tenant_id=tenant_id,
                subject_id=employee_id,
                as_of_date=as_of_date,
                strict_missing=strict_missing,
            )
            return report.model_copy(
                update={
                    "status": ResolutionStatus.SUBJECT_NOT_FOUND,
                    "report_warnings": [
                        f"Employee {employee_id!r} was not found in tenant {tenant_id!r}; no feature values were guessed."
                    ],
                }
            )

        provider = EmployeeContextValueProvider(context)
        return self.resolver.resolve(
            contract,
            provider=provider,
            tenant_id=tenant_id,
            subject_id=employee_id,
            employee_context=context,
            as_of_date=as_of_date,
            strict_missing=strict_missing,
        )

    def attrition_model_input(
        self,
        *,
        tenant_id: str,
        employee_id: str,
        as_of_date: date | None = None,
        strict_missing: bool = False,
    ) -> ModelInputEnvelope:
        report = self.resolve_attrition(
            tenant_id=tenant_id,
            employee_id=employee_id,
            as_of_date=as_of_date,
            strict_missing=strict_missing,
        )
        return self.attrition_adapter.adapt(report)
