"""Graph-first attrition adapter for the existing CatBoost service contract."""
from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from attrition_prediction_tool import (
    AttritionPredictionInput,
    AttritionPredictor,
    tool,
)
from feature_resolution.adapters import FeatureResolutionBlockedError
from feature_resolution.service import FeatureResolutionService


class GraphAttritionPredictionService:
    """Resolve CatBoost inputs from ontology/KG, then run the unchanged model."""

    def __init__(
        self,
        *,
        model_path: str | Path,
        feature_service: FeatureResolutionService,
        tenant_id: str,
        strict_missing: bool = False,
    ) -> None:
        self.predictor = AttritionPredictor(model_path)
        self.feature_service = feature_service
        self.tenant_id = tenant_id
        self.strict_missing = strict_missing

    @staticmethod
    def employee_id_from_record(employee_record: dict[str, Any]) -> str | None:
        employee = employee_record.get("employee")
        if isinstance(employee, dict):
            value = employee.get("employee_id") or employee.get("Employee_ID")
            if value not in (None, ""):
                return str(value).strip()

        records = employee_record.get("records")
        if isinstance(records, dict):
            for source_name in (
                "attrition_features",
                "profile",
                "performance",
                "attendance",
                "experience",
            ):
                source = records.get(source_name)
                if not isinstance(source, dict):
                    continue
                value = source.get("Employee_ID") or source.get("employeeId")
                if value not in (None, ""):
                    return str(value).strip()
        return None

    def predict_employee(self, employee_id: str) -> dict[str, Any]:
        try:
            envelope = self.feature_service.attrition_model_input(
                tenant_id=self.tenant_id,
                employee_id=str(employee_id).strip(),
                strict_missing=self.strict_missing,
            )
        except FeatureResolutionBlockedError:
            return {"attrition": None, "top_reasons": []}
        return self.predictor.predict_feature_values(envelope.values)

    def predict(self, employee_record: dict[str, Any]) -> dict[str, Any]:
        if employee_record.get("status") != "found":
            return {"attrition": None, "top_reasons": []}
        employee_id = self.employee_id_from_record(employee_record)
        if not employee_id:
            return {"attrition": None, "top_reasons": []}
        return self.predict_employee(employee_id)


def create_graph_attrition_prediction_tool(
    model_path: str | Path,
    *,
    feature_service: FeatureResolutionService,
    tenant_id: str,
    strict_missing: bool = False,
):
    service = GraphAttritionPredictionService(
        model_path=model_path,
        feature_service=feature_service,
        tenant_id=tenant_id,
        strict_missing=strict_missing,
    )

    @tool("predict_employee_attrition", args_schema=AttritionPredictionInput)
    def predict_employee_attrition(employee_record: dict[str, Any]) -> dict[str, Any]:
        """Predict attrition using ontology-resolved features from the Knowledge Graph.

        The external tool contract is unchanged: callers still pass the resolved
        employee record and receive attrition Yes/No plus the top reason names.
        """
        return service.predict(employee_record)

    return cast(Any, predict_employee_attrition)
