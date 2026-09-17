"""Feature-contract registry backed by the audited ontology service contracts."""
from __future__ import annotations

from functools import lru_cache

from ontology.registry import DEFAULT_REGISTRY, OntologyRegistry

from .models import FeatureContract, FeatureSpec, MissingPolicy


STEP8_CONTRACT_VERSION = "1.0.0-step8"


class FeatureContractRegistry:
    """Translate audited service contracts into Step-8 feature contracts.

    Only service contracts that already expose explicit per-feature ontology paths
    are materialized here. Step 8 does not infer feature contracts from prose,
    source filenames, or database columns.
    """

    def __init__(self, ontology: OntologyRegistry = DEFAULT_REGISTRY) -> None:
        self.ontology = ontology

    def list_contracts(self) -> list[str]:
        return ["attrition", "performance_recalculation"]

    @lru_cache(maxsize=8)
    def get(self, contract_name: str) -> FeatureContract:
        normalized = contract_name.strip().lower()
        if normalized == "attrition":
            return self._attrition()
        if normalized in {"performance", "performance_recalculation"}:
            return self._performance_recalculation()
        raise KeyError(
            f"Unknown Step-8 feature contract {contract_name!r}. "
            f"Available contracts: {', '.join(self.list_contracts())}"
        )

    def _feature_spec(
        self,
        *,
        order: int,
        feature_name: str,
        ontology_path: str,
        required: bool,
        missing_policy: MissingPolicy,
        model_type: str | None = None,
        unit: str | None = None,
        current_missing_behavior: str | None = None,
    ) -> FeatureSpec:
        prop = self.ontology.get_property(ontology_path)
        return FeatureSpec(
            order=order,
            feature_name=feature_name,
            ontology_path=ontology_path,
            model_type=model_type or prop.data_type,
            unit=unit or prop.unit,
            required=required,
            missing_policy=missing_policy,
            semantic_status=prop.semantic_status,
            derivable=bool(prop.derived),
            current_missing_behavior=current_missing_behavior,
        )

    def _attrition(self) -> FeatureContract:
        payload = self.ontology.get_service_contract("attrition")
        blocking = bool(payload.get("blocking_on_missing", True))
        features: list[FeatureSpec] = []
        for item in payload.get("features", []):
            required = bool(item.get("required_by_saved_model", True))
            if not required:
                policy = MissingPolicy.OPTIONAL
            elif blocking:
                policy = MissingPolicy.CRITICAL
            else:
                # Preserve the audited current CatBoost behavior. Missing numeric
                # values become NaN and the categorical value becomes "Missing".
                # The report still marks this as degraded instead of pretending
                # the semantic feature exists.
                policy = MissingPolicy.MODEL_NATIVE
            features.append(
                self._feature_spec(
                    order=int(item["order"]),
                    feature_name=str(item["current_feature"]),
                    ontology_path=str(item["ontology_path"]),
                    required=required,
                    missing_policy=policy,
                    model_type=str(item.get("model_type") or ""),
                    unit=item.get("unit"),
                    current_missing_behavior=item.get("current_missing_behavior"),
                )
            )
        return FeatureContract(
            service=str(payload.get("service", "attrition_prediction")),
            contract_name="attrition",
            source_contract="ontology/service_contracts/attrition.json",
            version=STEP8_CONTRACT_VERSION,
            features=features,
        )

    def _performance_recalculation(self) -> FeatureContract:
        payload = self.ontology.get_service_contract("performance")
        features: list[FeatureSpec] = []
        for order, item in enumerate(payload.get("recalculation_inputs", []), start=1):
            required = bool(item.get("required", False))
            features.append(
                self._feature_spec(
                    order=order,
                    feature_name=str(item["current_field"]),
                    ontology_path=str(item["ontology_path"]),
                    required=required,
                    missing_policy=(MissingPolicy.CRITICAL if required else MissingPolicy.OPTIONAL),
                )
            )
        return FeatureContract(
            service=str(payload.get("service", "employee_performance")),
            contract_name="performance_recalculation",
            source_contract="ontology/service_contracts/performance.json#recalculation_inputs",
            version=STEP8_CONTRACT_VERSION,
            features=features,
        )


DEFAULT_FEATURE_CONTRACTS = FeatureContractRegistry()
