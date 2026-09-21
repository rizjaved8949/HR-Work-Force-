"""Central Step-9 runtime wiring for existing HR AI services.

The current UI/API contracts remain unchanged. The manager swaps data/service
implementations behind those contracts according to an explicit runtime mode.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
import os

from feature_resolution.service import FeatureResolutionService
from semantic.service import SemanticHRService
from multi_org.context import tenant_resolver

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
        # Step 12 makes the graph-native adapters request-tenant aware while
        # retaining STEP9_TENANT_ID as the non-breaking default.  The
        # multi-org middleware sets a ContextVar after access validation.
        resolve_tenant = tenant_resolver(self.config.tenant_id)
        self.employee_search_tool = create_graph_employee_record_tool(
            self.semantic_service,
            tenant_id=resolve_tenant,
        )
        self.attrition_prediction_tool = create_graph_attrition_prediction_tool(
            self.model_path,
            feature_service=self.feature_service,
            tenant_id=resolve_tenant,
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
        compatibility_graph = (
            os.getenv("KG_RUNTIME_DATA_SOURCE", "legacy").strip().lower()
            == "knowledge_graph"
        )

        if graph_primary:
            employee_state = (
                ServiceMigrationState.GRAPH_FIRST_WITH_LEGACY_FALLBACK
                if fallback
                else ServiceMigrationState.GRAPH_NATIVE
            )
            employee_source = "knowledge_graph"
        elif compatibility_graph:
            # Even if the direct semantic adapter is not active, the old tool
            # contract can only see a tabular projection that was materialized
            # from the reserved KG runtime mirror. It never reads repository CSVs.
            employee_state = ServiceMigrationState.GRAPH_NATIVE
            employee_source = "knowledge_graph_runtime_projection"
        else:
            employee_state = ServiceMigrationState.LEGACY_DELEGATED
            employee_source = "legacy_csv"

        if compatibility_graph:
            compat_state = ServiceMigrationState.GRAPH_NATIVE
            compat_source = "knowledge_graph_runtime_projection"
            compat_fallback = False
        else:
            compat_state = ServiceMigrationState.HYBRID
            compat_source = None
            compat_fallback = True

        services = [
            ServiceMigrationStatus(
                service="employee_record_retrieval",
                state=employee_state,
                active_source=employee_source,
                graph_capable=True,
                fallback_enabled=fallback if not compatibility_graph else False,
                notes=[
                    "Existing get_employee_record tool and UI payload shape are preserved.",
                    "Graph mode resolves employee identity and related HR facts through SemanticHRService.",
                    *(
                        ["KG-only guard is enabled: repository CSV files are not a runtime fallback."]
                        if compatibility_graph else []
                    ),
                ],
            ),
            ServiceMigrationStatus(
                service="attrition_prediction",
                state=employee_state,
                active_source=employee_source,
                graph_capable=True,
                fallback_enabled=fallback if not compatibility_graph else False,
                notes=[
                    "CatBoost model, 14-feature order, threshold, missing-value behavior and SHAP reasons are unchanged.",
                    "Graph mode resolves model inputs through FeatureResolutionService before scoring.",
                ],
            ),
            ServiceMigrationStatus(
                service="employee_performance",
                state=compat_state,
                active_source=(
                    compat_source
                    if compatibility_graph
                    else "legacy_deterministic_service_with_step8_contract"
                ),
                graph_capable=True,
                fallback_enabled=compat_fallback,
                notes=(
                    [
                        "Existing deterministic Performance calculations are unchanged.",
                        "Their tabular inputs are a disposable compatibility projection rebuilt from the KG runtime mirror.",
                        "The LLM therefore receives Performance data whose runtime source is the Knowledge Graph.",
                    ]
                    if compatibility_graph
                    else [
                        "Step 8 feature contract is available for graph-backed recalculation inputs.",
                        "Live employee_performance_evidence_monthly was empty during Step 7 preflight, so KPI-evidence recalculation cannot be switched to graph without inventing data.",
                        "Existing deterministic Performance API remains active for UI continuity.",
                    ]
                ),
            ),
            ServiceMigrationStatus(
                service="headcount_management",
                state=compat_state,
                active_source=(
                    compat_source if compatibility_graph else "legacy_deterministic_service"
                ),
                graph_capable=True,
                fallback_enabled=compat_fallback,
                notes=(
                    [
                        "Headcount calculation code and API contracts are unchanged.",
                        "All source tables are materialized from the reserved KG runtime mirror before repository initialization.",
                    ]
                    if compatibility_graph
                    else [
                        "Core headcount facts exist in the graph; the current deterministic service remains the compatibility layer.",
                    ]
                ),
            ),
            ServiceMigrationStatus(
                service="scenario_simulation",
                state=compat_state,
                active_source=(
                    compat_source
                    if compatibility_graph
                    else "legacy_simulation_assumptions_plus_existing_hr_facts"
                ),
                graph_capable=True if compatibility_graph else False,
                fallback_enabled=compat_fallback,
                notes=(
                    [
                        "The seven deterministic simulation engines are unchanged.",
                        "Simulation datasets and assumptions are read from the KG runtime mirror projection, not repository CSV files.",
                    ]
                    if compatibility_graph
                    else [
                        "The five Data/Simulation datasets are a known Step 7/Supabase snapshot gap.",
                        "Simulation assumptions remain isolated read-only inputs; Step 9 does not invent graph facts for them.",
                    ]
                ),
            ),
            ServiceMigrationStatus(
                service="successor_replacement",
                state=compat_state,
                active_source=(
                    compat_source
                    if compatibility_graph
                    else "legacy_deterministic_successor_service"
                ),
                graph_capable=True,
                fallback_enabled=compat_fallback,
                notes=(
                    [
                        "Successor scoring/ranking logic is unchanged for score parity.",
                        "Its existing CSV-shaped inputs are reconstructed from the KG runtime mirror before the graph is built.",
                    ]
                    if compatibility_graph
                    else [
                        "Employee/skill/performance facts exist in the graph, but the existing ranking pipeline remains delegated.",
                    ]
                ),
            ),
        ]

        return Step9RuntimeStatus(
            mode=self.config.mode,
            tenant_id=self.config.tenant_id,
            graph_available=self.graph_available,
            services=services,
            warnings=list(self._warnings),
        )

