"""Deterministic budget analysis for Headcount Management.

This service calculates current workforce budgets and costs from
Department_Budget.csv. It does not call an LLM and does not change
the existing Attrition or replacement pipelines.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Final

import pandas as pd

from headcount.metric_registry import METRICS
from headcount.repository import HeadcountRepository
from headcount.schemas import (
    HeadcountMetricResult,
    HeadcountQueryPlan,
    HeadcountResultStatus,
    HeadcountToolResult,
    SortDirection,
)


class HeadcountBudgetError(RuntimeError):
    """Base error for Headcount budget analysis."""


class HeadcountBudgetScopeNotFoundError(
    HeadcountBudgetError
):
    """Raised when the requested budget scope is not found."""


BUDGET_METRICS: Final[set[str]] = {
    "total_approved_people_budget",
    "total_actual_people_cost",
    "remaining_people_budget",
    "budget_utilization_percentage",
    "approved_salary_and_benefits_budget",
    "recruitment_budget",
    "training_and_development_budget",
    "overtime_budget",
    "workforce_contingency_budget",
    "actual_salary_cost",
    "actual_benefits_cost",
    "actual_recruitment_cost",
    "actual_training_cost",
    "actual_overtime_cost",
}


BUDGET_COLUMN_MAP: Final[dict[str, str]] = {
    "total_approved_people_budget":
        "Total_Approved_People_Budget",

    "total_actual_people_cost":
        "Total_Actual_People_Cost",

    "remaining_people_budget":
        "Remaining_People_Budget",

    "approved_salary_and_benefits_budget":
        "Approved_Salary_and_Benefits_Budget",

    "recruitment_budget":
        "Recruitment_Budget",

    "training_and_development_budget":
        "Training_and_Development_Budget",

    "overtime_budget":
        "Overtime_Budget",

    "workforce_contingency_budget":
        "Workforce_Contingency_Budget",

    "actual_salary_cost":
        "Actual_Salary_Cost",

    "actual_benefits_cost":
        "Actual_Benefits_Cost",

    "actual_recruitment_cost":
        "Actual_Recruitment_Cost",

    "actual_training_cost":
        "Actual_Training_Cost",

    "actual_overtime_cost":
        "Actual_Overtime_Cost",
}


SUMMABLE_BUDGET_METRICS: Final[tuple[str, ...]] = (
    "total_approved_people_budget",
    "total_actual_people_cost",
    "remaining_people_budget",
    "approved_salary_and_benefits_budget",
    "recruitment_budget",
    "training_and_development_budget",
    "overtime_budget",
    "workforce_contingency_budget",
    "actual_salary_cost",
    "actual_benefits_cost",
    "actual_recruitment_cost",
    "actual_training_cost",
    "actual_overtime_cost",
)


class HeadcountBudgetService:
    """Execute deterministic current budget queries."""

    def __init__(
        self,
        repository: HeadcountRepository,
    ) -> None:
        self.repository = repository

    def execute(
        self,
        plan: HeadcountQueryPlan,
    ) -> HeadcountToolResult:
        """Execute one current Headcount budget query."""

        unsupported_metrics = [
            metric
            for metric in plan.metrics
            if metric not in BUDGET_METRICS
        ]

        if unsupported_metrics:
            return HeadcountToolResult(
                status=HeadcountResultStatus.UNSUPPORTED,
                question=plan.question,
                analysis_type=plan.analysis_type,
                message=(
                    "Some requested metrics are not supported "
                    "by the budget service."
                ),
                limitations=[
                    (
                        "Unsupported budget metrics: "
                        + ", ".join(unsupported_metrics)
                    )
                ],
                data_as_of_date=self._organization_as_of_date(),
            )

        if plan.date_range is not None:
            return HeadcountToolResult(
                status=HeadcountResultStatus.UNSUPPORTED,
                question=plan.question,
                analysis_type=plan.analysis_type,
                message=(
                    "Historical budget trends will be added "
                    "in the next service extension."
                ),
                limitations=[
                    (
                        "Step 6C currently uses the latest "
                        "available budget month."
                    )
                ],
                data_as_of_date=self._organization_as_of_date(),
            )

        unsupported_grouping = [
            dimension
            for dimension in plan.group_by
            if dimension not in {
                "department",
                "business_unit",
            }
        ]

        if unsupported_grouping:
            return HeadcountToolResult(
                status=HeadcountResultStatus.UNSUPPORTED,
                question=plan.question,
                analysis_type=plan.analysis_type,
                message=(
                    "Budget results can currently be grouped "
                    "by department or business unit."
                ),
                limitations=[
                    (
                        "Unsupported grouping dimensions: "
                        + ", ".join(unsupported_grouping)
                    )
                ],
                data_as_of_date=self._organization_as_of_date(),
            )

        if len(plan.group_by) > 1:
            return HeadcountToolResult(
                status=HeadcountResultStatus.UNSUPPORTED,
                question=plan.question,
                analysis_type=plan.analysis_type,
                message=(
                    "Only one budget grouping dimension is "
                    "supported at a time."
                ),
                data_as_of_date=self._organization_as_of_date(),
            )

        try:
            budget_frame = self._latest_budget_frame()

            scoped_frame, resolved_scope = (
                self._apply_scope(
                    budget_frame,
                    plan,
                )
            )

            summary_frame = self._aggregate(
                scoped_frame,
                group_by=None,
            )

            group_dimension = (
                plan.group_by[0]
                if plan.group_by
                else None
            )

            result_frame = self._aggregate(
                scoped_frame,
                group_by=group_dimension,
            )

            result_frame = self._sort_and_limit(
                dataframe=result_frame,
                plan=plan,
            )

            requested_metrics = (
                plan.metrics
                if plan.metrics
                else [
                    "total_approved_people_budget",
                    "total_actual_people_cost",
                    "remaining_people_budget",
                    "budget_utilization_percentage",
                ]
            )

            metric_results = self._create_metric_results(
                summary_frame.iloc[0],
                requested_metrics,
            )

            records = (
                self._create_records(
                    dataframe=result_frame,
                    metrics=requested_metrics,
                    group_by=group_dimension,
                )
                if plan.include_details
                else []
            )

            resolved_scope["group_by"] = (
                group_dimension or "organization"
            )

            resolved_scope["budget_month"] = (
                self._clean_value(
                    scoped_frame["budget_month"].max()
                )
            )

            return HeadcountToolResult(
                status=HeadcountResultStatus.SUCCESS,
                question=plan.question,
                analysis_type=plan.analysis_type,
                message=(
                    "Headcount budget analysis completed "
                    "successfully."
                ),
                resolved_scope=resolved_scope,
                metrics=metric_results,
                records=records,
                evidence_sources=[
                    "Department_Budget.csv",
                    "Department_Master.csv",
                ],
                data_as_of_date=self._budget_as_of_date(
                    scoped_frame
                ),
                calculation_notes=[
                    (
                        "The latest available budget month is "
                        "used unless a reporting period is requested."
                    ),
                    (
                        "Organization and business-unit budget "
                        "utilization is weighted: total actual people "
                        "cost divided by total approved people budget."
                    ),
                    (
                        "Budget utilization is not calculated by "
                        "averaging department percentages."
                    ),
                ],
            )

        except HeadcountBudgetScopeNotFoundError as error:
            return HeadcountToolResult(
                status=HeadcountResultStatus.NOT_FOUND,
                question=plan.question,
                analysis_type=plan.analysis_type,
                message=str(error),
                data_as_of_date=self._organization_as_of_date(),
            )

        except Exception as error:
            return HeadcountToolResult(
                status=HeadcountResultStatus.ERROR,
                question=plan.question,
                analysis_type=plan.analysis_type,
                message=(
                    "The Headcount budget calculation could "
                    "not be completed."
                ),
                limitations=[str(error)],
                data_as_of_date=self._organization_as_of_date(),
            )

    # ========================================================
    # DATA PREPARATION
    # ========================================================

    def _latest_budget_frame(self) -> pd.DataFrame:
        """Return one latest budget record per department."""

        budgets = self.repository.get_table(
            "department_budgets"
        )

        departments = self.repository.get_table(
            "departments"
        )

        budgets = budgets.copy()

        budgets["Budget_Month"] = pd.to_datetime(
            budgets["Budget_Month"],
            errors="coerce",
        )

        budgets["Data_As_Of_Date"] = pd.to_datetime(
            budgets["Data_As_Of_Date"],
            errors="coerce",
        )

        latest_month = budgets[
            "Budget_Month"
        ].max()

        latest = budgets[
            budgets["Budget_Month"].eq(latest_month)
        ].copy()

        department_reference = departments[
            [
                "Department_ID",
                "Business_Unit_Name",
            ]
        ].drop_duplicates(
            subset=["Department_ID"]
        )

        latest = latest.merge(
            department_reference,
            on="Department_ID",
            how="left",
        )

        latest = latest.rename(
            columns={
                "Budget_Month": "budget_month",
                "Data_As_Of_Date": "data_as_of_date",
                "Department_ID": "department_id",
                "Department_Name": "department",
                "Business_Unit_Name": "business_unit",
                "Cost_Center_ID": "cost_center_id",
                "Budget_Status": "budget_status",
                "Budget_Currency": "currency",
            }
        )

        for metric_name, source_column in (
            BUDGET_COLUMN_MAP.items()
        ):
            latest[metric_name] = pd.to_numeric(
                latest[source_column],
                errors="coerce",
            ).fillna(0)

        return self._add_derived_metrics(latest)

    @staticmethod
    def _add_derived_metrics(
        dataframe: pd.DataFrame,
    ) -> pd.DataFrame:
        """Calculate weighted budget utilization."""

        result = dataframe.copy()

        approved_budget = result[
            "total_approved_people_budget"
        ].replace(0, pd.NA)

        result["budget_utilization_percentage"] = (
            (
                result["total_actual_people_cost"]
                / approved_budget
            )
            * 100
        ).round(2).fillna(0.0)

        return result

    # ========================================================
    # SCOPE
    # ========================================================

    def _apply_scope(
        self,
        dataframe: pd.DataFrame,
        plan: HeadcountQueryPlan,
    ) -> tuple[pd.DataFrame, dict[str, Any]]:
        """Apply department and business-unit scope."""

        result = dataframe.copy()

        resolved_scope: dict[str, Any] = {
            "organization": "All",
        }

        requested_department = plan.scope.department

        if requested_department is None:
            requested_department = (
                self._find_name_in_question(
                    question=plan.question,
                    values=dataframe["department"],
                )
            )

        if requested_department is not None:
            result = self._filter_named_scope(
                dataframe=result,
                requested_value=requested_department,
                id_column="department_id",
                name_column="department",
                scope_label="department",
            )

            resolved_scope["department"] = (
                result["department"].iloc[0]
            )

        requested_business_unit = (
            plan.scope.business_unit
        )

        if requested_business_unit is None:
            requested_business_unit = (
                self._find_name_in_question(
                    question=plan.question,
                    values=dataframe["business_unit"],
                )
            )

        if requested_business_unit is not None:
            result = self._filter_named_scope(
                dataframe=result,
                requested_value=requested_business_unit,
                id_column=None,
                name_column="business_unit",
                scope_label="business unit",
            )

            resolved_scope["business_unit"] = (
                result["business_unit"].iloc[0]
            )

        if result.empty:
            raise HeadcountBudgetScopeNotFoundError(
                "No budget data was found for the requested scope."
            )

        return result, resolved_scope

    @staticmethod
    def _filter_named_scope(
        *,
        dataframe: pd.DataFrame,
        requested_value: str,
        id_column: str | None,
        name_column: str,
        scope_label: str,
    ) -> pd.DataFrame:
        """Resolve a scope by exact or unique partial matching."""

        normalized_value = (
            str(requested_value)
            .strip()
            .casefold()
        )

        name_values = (
            dataframe[name_column]
            .astype("string")
            .str.strip()
            .str.casefold()
        )

        exact_mask = name_values.eq(
            normalized_value
        )

        if id_column is not None:
            id_values = (
                dataframe[id_column]
                .astype("string")
                .str.strip()
                .str.casefold()
            )

            exact_mask = (
                exact_mask
                | id_values.eq(normalized_value)
            )

        exact_matches = dataframe[
            exact_mask
        ]

        if not exact_matches.empty:
            return exact_matches.copy()

        partial_matches = dataframe[
            name_values.str.contains(
                re.escape(normalized_value),
                regex=True,
                na=False,
            )
        ]

        unique_names = partial_matches[
            name_column
        ].dropna().unique()

        if len(unique_names) == 1:
            return partial_matches.copy()

        raise HeadcountBudgetScopeNotFoundError(
            f"The requested {scope_label} "
            f"{requested_value!r} was not found uniquely."
        )

    @staticmethod
    def _find_name_in_question(
        *,
        question: str,
        values: pd.Series,
    ) -> str | None:
        """Find complete known names using word boundaries."""

        normalized_question = re.sub(
            r"\s+",
            " ",
            question.casefold(),
        ).strip()

        known_values = sorted(
            {
                str(value).strip()
                for value in values.dropna().unique()
                if str(value).strip()
            },
            key=len,
            reverse=True,
        )

        for known_value in known_values:
            normalized_value = re.sub(
                r"\s+",
                " ",
                known_value.casefold(),
            ).strip()

            pattern = (
                rf"(?<!\w)"
                rf"{re.escape(normalized_value)}"
                rf"(?!\w)"
            )

            if re.search(
                pattern,
                normalized_question,
            ):
                return known_value

        return None

    # ========================================================
    # AGGREGATION
    # ========================================================

    def _aggregate(
        self,
        dataframe: pd.DataFrame,
        group_by: str | None,
    ) -> pd.DataFrame:
        """Aggregate budgets at the requested level."""

        if group_by == "department":
            return dataframe.copy()

        if group_by == "business_unit":
            grouped = (
                dataframe
                .groupby(
                    "business_unit",
                    dropna=False,
                )[list(SUMMABLE_BUDGET_METRICS)]
                .sum()
                .reset_index()
            )

            return self._add_derived_metrics(
                grouped
            )

        totals = {
            metric: dataframe[metric].sum()
            for metric in SUMMABLE_BUDGET_METRICS
        }

        result = pd.DataFrame([totals])

        result.insert(
            0,
            "organization",
            "All",
        )

        return self._add_derived_metrics(result)

    @staticmethod
    def _sort_and_limit(
        *,
        dataframe: pd.DataFrame,
        plan: HeadcountQueryPlan,
    ) -> pd.DataFrame:
        """Sort and limit grouped results."""

        result = dataframe.copy()

        if (
            plan.sort_by is not None
            and plan.sort_by in result.columns
        ):
            ascending = (
                plan.sort_direction
                == SortDirection.ASCENDING
            )

            result = result.sort_values(
                by=plan.sort_by,
                ascending=ascending,
                na_position="last",
            )

        if plan.group_by:
            result = result.head(
                plan.limit
            )

        return result.reset_index(
            drop=True
        )

    # ========================================================
    # RESULT CREATION
    # ========================================================

    def _create_metric_results(
        self,
        summary_row: pd.Series,
        metrics: list[str],
    ) -> list[HeadcountMetricResult]:
        """Create exact structured metric results."""

        results: list[
            HeadcountMetricResult
        ] = []

        for metric_name in metrics:
            if metric_name not in summary_row.index:
                continue

            definition = METRICS[
                metric_name
            ]

            numerator: int | float | None = None
            denominator: int | float | None = None

            if (
                metric_name
                == "budget_utilization_percentage"
            ):
                numerator = self._number_value(
                    summary_row[
                        "total_actual_people_cost"
                    ]
                )

                denominator = self._number_value(
                    summary_row[
                        "total_approved_people_budget"
                    ]
                )

            results.append(
                HeadcountMetricResult(
                    metric_name=metric_name,
                    display_name=(
                        definition.display_name
                    ),
                    value=self._clean_value(
                        summary_row[metric_name]
                    ),
                    unit=definition.unit,
                    numerator=numerator,
                    denominator=denominator,
                )
            )

        return results

    def _create_records(
        self,
        *,
        dataframe: pd.DataFrame,
        metrics: list[str],
        group_by: str | None,
    ) -> list[dict[str, Any]]:
        """Create JSON-safe budget records."""

        if group_by == "department":
            identity_columns = [
                "department_id",
                "department",
                "business_unit",
                "cost_center_id",
                "budget_status",
                "currency",
                "budget_month",
            ]

        elif group_by == "business_unit":
            identity_columns = [
                "business_unit",
            ]

        else:
            identity_columns = [
                "organization",
            ]

        selected_columns = [
            column
            for column in (
                identity_columns + metrics
            )
            if column in dataframe.columns
        ]

        records: list[
            dict[str, Any]
        ] = []

        raw_records = dataframe[
            selected_columns
        ].to_dict(
            orient="records"
        )

        for record in raw_records:
            records.append({
                str(key): self._clean_value(value)
                for key, value in record.items()
            })

        return records

    # ========================================================
    # HELPERS
    # ========================================================

    @staticmethod
    def _number_value(
        value: Any,
    ) -> int | float | None:
        clean_value = (
            HeadcountBudgetService
            ._clean_value(value)
        )

        if isinstance(
            clean_value,
            (int, float),
        ):
            return clean_value

        return None

    @staticmethod
    def _clean_value(
        value: Any,
    ) -> Any:
        """Convert pandas values into JSON-safe values."""

        if value is None:
            return None

        try:
            if pd.isna(value):
                return None
        except (TypeError, ValueError):
            pass

        if isinstance(value, pd.Timestamp):
            return value.date().isoformat()

        if isinstance(value, date):
            return value.isoformat()

        if hasattr(value, "item"):
            value = value.item()

        if isinstance(value, float):
            if value.is_integer():
                return int(value)

            return round(value, 2)

        return value

    @staticmethod
    def _budget_as_of_date(
        dataframe: pd.DataFrame,
    ) -> date | None:
        if (
            "data_as_of_date"
            not in dataframe.columns
            or dataframe.empty
        ):
            return None

        value = dataframe[
            "data_as_of_date"
        ].max()

        if pd.isna(value):
            return None

        return pd.Timestamp(
            value
        ).date()

    def _organization_as_of_date(
        self,
    ) -> date | None:
        value = (
            self.repository
            .get_data_as_of_date()
        )

        if value is None:
            return None

        try:
            return date.fromisoformat(value)
        except ValueError:
            return None