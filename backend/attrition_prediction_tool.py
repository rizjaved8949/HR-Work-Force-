from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from catboost import CatBoostClassifier, Pool
from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

EXPECTED_FEATURES = [
    "Tenure_Months",
    "Monthly_Salary_PKR",
    "Salary_vs_Market_pct",
    "Last_Increment_pct",
    "Months_Since_Last_Promotion",
    "KPI_Achievement_pct",
    "Performance_Trend_6M",
    "Overtime_Hours_Last_30D",
    "Engagement_Score",
    "Job_Satisfaction_Score",
    "Work_Life_Balance_Score",
    "Manager_Relationship_Score",
    "Career_Growth_Score",
    "Pay_Concern_Raised_Last_6M",
]

CATEGORICAL_FEATURES = ["Pay_Concern_Raised_Last_6M"]
NUMERICAL_FEATURES = [f for f in EXPECTED_FEATURES if f not in CATEGORICAL_FEATURES]
TARGET_COLUMN = "Will_Resign_in_Next_6_Months"


class AttritionPredictionInput(BaseModel):
    employee_record: dict[str, Any] = Field(
        ...,
        description="Complete structured output returned by get_employee_record.",
    )


class AttritionPredictor:
    def __init__(self, model_path: str | Path):
        self.model_path = Path(model_path)
        if not self.model_path.exists():
            raise FileNotFoundError(f"CatBoost model was not found: {self.model_path}")

        self.model = CatBoostClassifier()
        self.model.load_model(str(self.model_path))

        stored_feature_names = list(getattr(self.model, "feature_names_", []) or [])
        if stored_feature_names:
            missing_from_model = [
                feature for feature in EXPECTED_FEATURES
                if feature not in stored_feature_names
            ]
            unexpected_in_model = [
                feature for feature in stored_feature_names
                if feature not in EXPECTED_FEATURES
            ]
            if missing_from_model or unexpected_in_model:
                raise ValueError(
                    "Saved model feature schema does not match the configured 14 features. "
                    f"Missing from model: {missing_from_model}; "
                    f"Unexpected in model: {unexpected_in_model}"
                )
            self.feature_order = stored_feature_names
        else:
            self.feature_order = EXPECTED_FEATURES.copy()

    @staticmethod
    def _to_float(value: Any) -> float:
        if value is None:
            return np.nan
        if isinstance(value, str):
            value = value.strip().replace(",", "")
            if not value:
                return np.nan
        try:
            return float(value)
        except (TypeError, ValueError):
            return np.nan

    @staticmethod
    def _normalize_yes_no(value: Any) -> str:
        if value is None:
            return "Missing"
        normalized = str(value).strip().casefold()
        if normalized in {"yes", "y", "1", "true"}:
            return "Yes"
        if normalized in {"no", "n", "0", "false"}:
            return "No"
        if not normalized:
            return "Missing"
        return str(value).strip()

    @staticmethod
    def _get_source_records(employee_record: dict[str, Any]) -> list[dict[str, Any]]:
        records = employee_record.get("records", {})
        source_names = [
            "attrition_features",
            "profile",
            "attendance",
            "performance",
            "experience",
        ]
        output: list[dict[str, Any]] = []
        for source_name in source_names:
            source = records.get(source_name, {})
            if isinstance(source, dict):
                output.append(source)
        return output

    def _extract_features(
        self,
        employee_record: dict[str, Any],
    ) -> tuple[pd.DataFrame, list[str], dict[str, Any]]:
        collected: dict[str, Any] = {}

        for source in self._get_source_records(employee_record):
            for feature in EXPECTED_FEATURES:
                if (
                    feature not in collected
                    and feature in source
                    and source[feature] not in (None, "")
                ):
                    collected[feature] = source[feature]

        originally_missing = [
            feature for feature in EXPECTED_FEATURES
            if feature not in collected
        ]

        prepared: dict[str, Any] = {}
        for feature in self.feature_order:
            raw_value = collected.get(feature)
            if feature in CATEGORICAL_FEATURES:
                prepared[feature] = self._normalize_yes_no(raw_value)
            else:
                prepared[feature] = self._to_float(raw_value)

        input_frame = pd.DataFrame([prepared], columns=self.feature_order)
        return input_frame, originally_missing, prepared

    def _build_reasons(
        self,
        model_pool: Pool,
        predicted_label: str,
        limit: int = 3,
    ) -> list[str]:
        """
        Return only the top feature names that pushed the
        prediction toward attrition = Yes.
        """
        if predicted_label != "Yes":
            return []

        shap_output = np.asarray(
            self.model.get_feature_importance(
                data=model_pool,
                type="ShapValues",
            )
        )

        if shap_output.ndim != 2:
            return []

        contributions = shap_output[0, :-1]

        ranked_features = [
            (feature, float(contribution))
            for feature, contribution in zip(
                self.feature_order,
                contributions,
            )
            if float(contribution) > 0
        ]

        ranked_features.sort(
            key=lambda item: item[1],
            reverse=True,
        )

        return [
            feature
            for feature, _ in ranked_features[:limit]
        ]

    def predict(
        self,
        employee_record: dict[str, Any],
    ) -> dict[str, Any]:
        upstream_status = employee_record.get("status")

        if upstream_status != "found":
            return {
                "attrition": None,
                "top_reasons": [],
            }

        input_frame, _, _ = self._extract_features(
            employee_record
        )

        model_pool = Pool(
            data=input_frame,
            cat_features=CATEGORICAL_FEATURES,
            feature_names=self.feature_order,
        )

        attrition_probability = float(
            self.model.predict_proba(model_pool)[0, 1]
        )

        predicted_label = (
            "Yes"
            if attrition_probability >= 0.50
            else "No"
        )

        top_reasons = self._build_reasons(
            model_pool=model_pool,
            predicted_label=predicted_label,
            limit=3,
        )

        return {
            "attrition": predicted_label,
            "top_reasons": top_reasons,
        }


def create_attrition_prediction_tool(model_path: str | Path) -> BaseTool:
    predictor = AttritionPredictor(model_path)

    @tool(
        "predict_employee_attrition",
        args_schema=AttritionPredictionInput,
    )
    def predict_employee_attrition(
        employee_record: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Predict whether a resolved employee is likely to resign in the next
        six months. Pass the complete output returned by get_employee_record.
        The tool selects the exact CatBoost features, prepares missing values,
        calls the saved model, and returns only attrition Yes/No plus the top feature names.
        """
        return predictor.predict(employee_record)

    return predict_employee_attrition
