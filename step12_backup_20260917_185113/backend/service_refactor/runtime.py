"""Central Step-9 runtime wiring for existing HR AI services.

The current UI/API contracts remain unchanged. The manager swaps data/service
implementations behind those contracts according to an explicit runtime mode.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from feature_resolution.service import FeatureResolutionService
from semantic.service import SemanticHRService

from .attrition import create_graph_attrition_prediction_tool
from .config import Step9RuntimeConfig
from .employee import create_graph_employee_record_tool
from .models import (
    RuntimeMode,
    ServiceMigrationState,
    ServiceMigrationStatus,
    Step9RuntimeStatus,
)


class Step9RuntimeManager:
    def __init__(
        self,
        *,
        config: Step9RuntimeConfig,
        model_path: str | Path,
        legacy_employee_search_tool: Any,
        legacy_attrition_prediction_tool: Any,
        legacy_headcount_service: Any = None,
        legacy_performance_service: Any = None,
        legacy_simulation_service: Any = None,
        legacy_simulation_data_service: Any = None,
        legacy_simulation_lookup_service: Any = None,
        legacy_replacement_tool: Any = None,
        semantic_service: SemanticHRService | None = None,
        feature_service: FeatureResolutionService | None = None,
    ) -> None:
        self.config = config
        self.model_path = Path(model_path)
        self._legacy_employee_search_tool = legacy_employee_search_tool
        self._legacy_attrition_prediction_tool = legacy_attrition_prediction_tool
        self.headcount_service = legacy_headcount_service
        self.performance_service = legacy_performance_service
        self.simulation_service = legacy_simulation_service
        self.simulation_data_service = legacy_simulation_data_service
        self.simulation_lookup_service = legacy_simulation_lookup_service
        self.replacement_tool = legacy_replacement_tool

        self.semantic_service = semantic_service
        self.feature_service = feature_service
        self.graph_available = False
        self._warnings: list[str] = []

        self.employee_search_tool = legacy_employee_search_tool
        self.attrition_prediction_tool = legacy_attrition_prediction_tool

        self._initialize_graph_runtime()

    @classmethod
    def build(
        cls,
        *,
        model_path: str | Path,
        legacy_employee_search_tool: Any,
        legacy_attrition_prediction_tool: Any,
        legacy_headcount_service: Any = None,
        legacy_performance_service: Any = None,
        legacy_simulation_service: Any = None,
        legacy_simulation_data_service: Any = None,
        legacy_simulation_lookup_service: Any = None,
        legacy_replacement_tool: Any = None,
        config: Step9RuntimeConfig | None = None,
    ) -> "Step9RuntimeManager":
        return cls(
            config=config or Step9RuntimeConfig.from_env(),
            model_path=model_path,
            legacy_employee_search_tool=legacy_employee_search_tool,
            legacy_attrition_prediction_tool=legacy_attrition_prediction_tool,
            legacy_headcount_service=legacy_headcount_service,
            legacy_performance_service=legacy_performance_service,
            legacy_simulation_service=legacy_simulation_service,
            legacy_simulation_data_service=legacy_simulation_data_service,
            legacy_simulation_lookup_service=legacy_simulation_lookup_service,
            legacy_replacement_tool=legacy_replacement_tool,
        )

    def _initialize_graph_runtime(self) -> None:
        if self.config.mode == RuntimeMode.LEGACY:
            return

        try:
            if self.feature_service is not None and self.semantic_service is None:
                self.semantic_service = self.feature_service.semantic_service
            if self.semantic_service is None:
                self.semantic_service = SemanticHRService.from_env(
                    verify_connectivity=self.config.verify_graph_connectivity
                )
            if self.feature_service is None:
                self.feature_service = FeatureResolutionService(self.semantic_service)
            if self.config.verify_graph_connectivity:
                health = self.semantic_service.health(self.config.tenant_id)
                if int(health.get("node_count") or 0) <= 0:
                    raise RuntimeError(
                        f"Knowledge Graph has no nodes for tenant {self.config.tenant_id!r}. "
                        "Finish Step 7 live load before graph-first Step 9 runtime."
                    )
            self.graph_available = True
        except Exception as error:
            self.graph_available = False
            if self.config.mode == RuntimeMode.GRAPH_ONLY or not self.config.allow_legacy_fallback:
                raise RuntimeError(
                    "Step 9 graph runtime could not initialize and legacy fallback is disabled: "
                    f"{error}"
                ) from error
            self._warnings.append(
                "Graph-first initialization failed; employee search and attrition remain on the "
                f"legacy runtime for this process. Reason: {error}"
            )
            return

        assert self.semantic_service is not None
        assert self.feature_service is not None
        self.employee_search_tool = create_graph_employee_record_tool(
            self.semantic_service,
            tenant_id=self.config.tenant_id,
        )
        self.attrition_prediction_tool = create_graph_attrition_prediction_tool(
            self.model_path,
            feature_service=self.feature_service,
            tenant_id=self.config.tenant_id,
        )

    def close(self) -> None:
        # FeatureResolutionService and SemanticHRService normally share the same
        # repository. Close it once through the feature service when present.
        if self.feature_service is not None:
            self.feature_service.close()
        elif self.semantic_service is not None:
            self.semantic_service.close()

    def status(self) -> Step9RuntimeStatus:
        graph_primary = self.graph_available and self.config.mode != RuntimeMode.LEGACY
        fallback = self.config.mode == RuntimeMode.GRAPH_FIRST and self.config.allow_legacy_fallback

        if graph_primary:
            employee_state = (
                ServiceMigrationState.GRAPH_FIRST_WITH_LEGACY_FALLBACK
                if fallback
                else ServiceMigrationState.GRAPH_NATIVE
            )
            employee_source = "knowledge_graph"
        else:
            employee_state = ServiceMigrationState.LEGACY_DELEGATED
            employee_source = "legacy_csv"

        services = [
            ServiceMigrationStatus(
                service="employee_record_retrieval",
                state=employee_state,
                active_source=employee_source,
                graph_capable=True,
                fallback_enabled=fallback,
                notes=[
                    "Existing get_employee_record tool and UI payload shape are preserved.",
                    "Graph mode resolves employee identity and related HR facts through SemanticHRService.",
                ],
            ),
            ServiceMigrationStatus(
                service="attrition_prediction",
                state=employee_state,
                active_source=employee_source,
                graph_capable=True,
                fallback_enabled=fallback,
                notes=[
                    "CatBoost model, 14-feature order, threshold, missing-value behavior and SHAP reasons are unchanged.",
                    "Graph mode resolves model inputs through FeatureResolutionService before scoring.",
                ],
            ),
            ServiceMigrationStatus(
                service="employee_performance",
                state=ServiceMigrationState.HYBRID,
                active_source="legacy_deterministic_service_with_step8_contract",
                graph_capable=True,
                fallback_enabled=True,
                notes=[
                    "Step 8 feature contract is available for graph-backed recalculation inputs.",
                    "Live employee_performance_evidence_monthly was empty during Step 7 preflight, so KPI-evidence recalculation cannot be switched to graph without inventing data.",
                    "Existing deterministic Performance API remains active for UI continuity.",
                ],
            ),
            ServiceMigrationStatus(
                service="headcount_management",
                state=ServiceMigrationState.HYBRID,
                active_source="legacy_deterministic_service",
                graph_capable=True,
                fallback_enabled=True,
                notes=[
                    "Core headcount snapshots, positions, budgets, activities, demand drivers, exceptions and rules are present in the graph.",
                    "Current summary/metric-definition datasets are derived or intentionally not loaded; existing deterministic service remains the compatibility calculation layer in Step 9.",
                ],
            ),
            ServiceMigrationStatus(
                service="scenario_simulation",
                state=ServiceMigrationState.HYBRID,
                active_source="legacy_simulation_assumptions_plus_existing_hr_facts",
                graph_capable=False,
                fallback_enabled=True,
                notes=[
                    "The five Data/Simulation datasets are a known Step 7/Supabase snapshot gap.",
                    "Simulation assumptions remain isolated read-only inputs; Step 9 does not invent graph facts for them.",
                ],
            ),
            ServiceMigrationStatus(
                service="successor_replacement",
                state=ServiceMigrationState.HYBRID,
                active_source="legacy_deterministic_successor_service",
                graph_capable=True,
                fallback_enabled=True,
                notes=[
                    "Employee/skill/performance facts exist in the graph, but the existing ranking pipeline is retained until its full parity contract is migrated without changing scores.",
                ],
            ),
        ]

        return Step9RuntimeStatus(
            mode=self.config.mode,
            tenant_id=self.config.tenant_id,
            graph_available=self.graph_available,
            services=services,
            warnings=list(self._warnings),
        )
