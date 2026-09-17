"""Model adapters that preserve existing saved-model contracts after semantic resolution."""
from __future__ import annotations

import math
from typing import Any

from .models import FeatureResolutionReport, ModelInputEnvelope, ResolutionStatus


class FeatureResolutionBlockedError(RuntimeError):
    """Raised when a model adapter is asked to consume a blocked feature report."""


def _to_float(value: Any) -> float:
    if value is None:
        return math.nan
    if isinstance(value, str):
        value = value.strip().replace(",", "")
        if not value:
            return math.nan
    try:
        return float(value)
    except (TypeError, ValueError):
        return math.nan


def _yes_no(value: Any) -> str:
    if value is None:
        return "Missing"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    normalized = str(value).strip().casefold()
    if normalized in {"yes", "y", "1", "true"}:
        return "Yes"
    if normalized in {"no", "n", "0", "false"}:
        return "No"
    if not normalized:
        return "Missing"
    return str(value).strip()


class AttritionCatBoostAdapter:
    """Convert ontology-resolved features to the exact current CatBoost schema.

    This does not run CatBoost. Step 9 will connect the existing prediction
    service to this adapter after parity tests.
    """

    adapter_name = "attrition_catboost_v1"
    categorical_feature = "Pay_Concern_Raised_Last_6M"

    def adapt(self, report: FeatureResolutionReport) -> ModelInputEnvelope:
        if report.contract_name != "attrition":
            raise ValueError(
                f"AttritionCatBoostAdapter requires attrition report, found {report.contract_name!r}"
            )
        if report.status in {ResolutionStatus.BLOCKED, ResolutionStatus.SUBJECT_NOT_FOUND}:
            missing = [
                item.feature_name
                for item in report.features
                if not item.resolved
            ]
            raise FeatureResolutionBlockedError(
                "Attrition model input is blocked by the feature resolver. "
                f"Unresolved features: {missing}"
            )

        ordered = sorted(report.features, key=lambda item: item.order)
        values: dict[str, Any] = {}
        unresolved: list[str] = []
        notes: list[str] = []

        for item in ordered:
            raw = item.value if item.resolved else None
            if not item.resolved:
                unresolved.append(item.feature_name)
            if item.feature_name == self.categorical_feature:
                values[item.feature_name] = _yes_no(raw)
            else:
                values[item.feature_name] = _to_float(raw)

        if unresolved:
            notes.append(
                "Current audited CatBoost missing-value behavior preserved: numeric -> NaN; "
                "Pay_Concern_Raised_Last_6M -> 'Missing'."
            )
        if any(item.semantic_status != "confirmed" for item in ordered):
            notes.append(
                "At least one ontology feature has unresolved semantic metadata; values are passed "
                "through without invented normalization."
            )

        return ModelInputEnvelope(
            service=report.service,
            adapter=self.adapter_name,
            ready=True,
            feature_order=[item.feature_name for item in ordered],
            values=values,
            unresolved_features=unresolved,
            notes=notes,
        )


DEFAULT_ATTRITION_ADAPTER = AttritionCatBoostAdapter()
