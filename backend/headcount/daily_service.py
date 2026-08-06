"""Deterministic daily workforce availability analysis.

This service uses Daily_Headcount_Activity.csv to answer questions
about employee availability, leave, absence, overtime, and daily
open positions.

It does not call an LLM and does not modify Attrition services.
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


class HeadcountDailyError(RuntimeError):
    """Base error for daily Headcount activity analysis."""


class HeadcountDailyScopeNotFoundError(
    HeadcountDailyError
):
    """Raised when no daily data matches the requested scope."""


DAILY_ACTIVITY_METRICS: Final[set[str]] = {
    "actual_employee_count",
    "employees_available_for_work",
    "employees_on_approved_leave",
    "employees_absent",
    "total_overtime_hours",
    "workforce_availability_percentage",
    "daily_open_position_count",
    "daily_critical_open_position_count",
}


DAILY_ONLY_METRICS: Final[set[str]] = {
    "employees_available_for_work",
    "employees_on_approved_leave",
    "employees_absent",
    "total_overtime_hours",
    "workforce_availability_percentage",
    "daily_open_position_count",
    "daily_critical_open_position_count",
}


DAILY_FLOW_METRICS: Final[tuple[str, ...]] = (
    "employees_available_for_work",
    "employees_on_approved_leave",
    "employees_absent",
    "total_overtime_hours",
)


DAILY_STOCK_METRICS: Final[tuple[str, ...]] = (
    "actual_employee_count",
    "daily_open_position_count",
    "daily_critical_open_position_count",
)


class HeadcountDailyService:
    """Execute deterministic daily workforce queries."""

    def __init__(
        self,
        repository: HeadcountRepository,
    ) -> None:
        self.repository = repository

    def execute(
        self,
        plan: HeadcountQueryPlan,
    ) -> HeadcountToolResult:
        """Execute one daily workforce-availability query."""

        unsupported_metrics = [
            metric
            for metric in plan.metrics
            if metric not in DAILY_ACTIVITY_METRICS
        ]

        if unsupported_metrics:
            return HeadcountToolResult(
                status=HeadcountResultStatus.UNSUPPORTED,
                question=plan.question,
                analysis_type=plan.analysis_type,
                message=(
                    "Some requested metrics are not supported "
                    "by the daily activity service."
                ),
                limitations=[
                    (
                        "Unsupported daily metrics: "
                        + ", ".join(unsupported_metrics)
                    )
                ],
                data_as_of_date=self._organization_as_of_date(),
            )

        unsupported_grouping = [
            dimension
            for dimension in plan.group_by
            if dimension not in {
                "activity_date",
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
                    "Daily activity can currently be grouped by "
                    "date, department, or business unit."
                ),
                limitations=[
                    (
                        "Unsupported daily grouping dimensions: "
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
                    "Only one daily grouping dimension is "
                    "supported at a time."
                ),
                data_as_of_date=self._organization_as_of_date(),
            )

        try:
            activity = self._prepare_activity()

            activity, resolved_scope = self._apply_scope(
                activity,
                plan,
            )

            activity = self._apply_date_range(
                activity,
                plan,
            )

            if activity.empty:
                raise HeadcountDailyScopeNotFoundError(
                    "No daily workforce activity was found for "
                    "the requested scope and period."
                )

            requested_metrics = (
                plan.metrics
                if plan.metrics
                else [
                    "actual_employee_count",
                    "employees_available_for_work",
                    "employees_on_approved_leave",
                    "employees_absent",
                    "total_overtime_hours",
                    "workforce_availability_percentage",
                    "daily_open_position_count",
                    "daily_critical_open_position_count",
                ]
            )

            group_dimension = (
                plan.group_by[0]
                if plan.group_by
                else None
            )

            result_frame = self._aggregate(
                activity,
                group_by=group_dimension,
            )

            result_frame = self._sort_and_limit(
                dataframe=result_frame,
                plan=plan,
            )

            summary_frame = self._aggregate(
                activity,
                group_by=None,
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

            resolved_scope["start_date"] = (
                activity["activity_date"]
                .min()
                .date()
                .isoformat()
            )

            resolved_scope["end_date"] = (
                activity["activity_date"]
                .max()
                .date()
                .isoformat()
            )

            return HeadcountToolResult(
                status=HeadcountResultStatus.SUCCESS,
                question=plan.question,
                analysis_type=plan.analysis_type,
                message=(
                    "Daily workforce availability analysis "
                    "completed successfully."
                ),
                resolved_scope=resolved_scope,
                metrics=metric_results,
                records=records,
                evidence_sources=[
                    "Daily_Headcount_Activity.csv",
                    "Department_Master.csv",
                ],
                data_as_of_date=self._activity_as_of_date(
                    activity
                ),
                calculation_notes=[
                    (
                        "When no date is requested, the latest "
                        "available activity date is used."
                    ),
                    (
                        "Availability percentage is weighted: "
                        "available employee-days divided by total "
                        "employee-days."
                    ),
                    (
                        "Open-position counts represent the latest "
                        "date in the selected period."
                    ),
                    (
                        "Overtime, absence, leave, and availability "
                        "counts are summed across the selected period."
                    ),
                ],
            )

        except HeadcountDailyScopeNotFoundError as error:
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
                    "Daily workforce activity analysis could "
                    "not be completed."
                ),
                limitations=[str(error)],
                data_as_of_date=self._organization_as_of_date(),
            )

    # ========================================================
    # DATA PREPARATION
    # ========================================================

    def _prepare_activity(self) -> pd.DataFrame:
        activity = self.repository.get_table(
            "daily_activity"
        ).copy()

        departments = self.repository.get_table(
            "departments"
        )

        activity = activity.rename(
            columns={
                "Activity_Date": "activity_date",
                "Department_ID": "department_id",
                "Department_Name": "department",
                "Actual_Employee_Count":
                    "actual_employee_count",
                "Employees_Available_for_Work":
                    "employees_available_for_work",
                "Employees_on_Approved_Leave":
                    "employees_on_approved_leave",
                "Employees_Absent":
                    "employees_absent",
                "Total_Overtime_Hours":
                    "total_overtime_hours",
                "Open_Position_Count":
                    "daily_open_position_count",
                "Critical_Open_Position_Count":
                    "daily_critical_open_position_count",
                "Workforce_Availability_Percentage":
                    "workforce_availability_percentage",
                "Data_Refresh_Timestamp":
                    "data_refresh_timestamp",
                "Data_Quality_Status":
                    "data_quality_status",
            }
        )

        activity["activity_date"] = pd.to_datetime(
            activity["activity_date"],
            errors="coerce",
        )

        activity["data_refresh_timestamp"] = pd.to_datetime(
            activity["data_refresh_timestamp"],
            errors="coerce",
        )

        numeric_columns = [
            *DAILY_FLOW_METRICS,
            *DAILY_STOCK_METRICS,
        ]

        for column in numeric_columns:
            activity[column] = pd.to_numeric(
                activity[column],
                errors="coerce",
            ).fillna(0)

        department_reference = departments[
            [
                "Department_ID",
                "Business_Unit_Name",
            ]
        ].drop_duplicates(
            subset=["Department_ID"]
        ).rename(
            columns={
                "Department_ID": "department_id",
                "Business_Unit_Name": "business_unit",
            }
        )

        activity = activity.merge(
            department_reference,
            on="department_id",
            how="left",
        )

        return activity

    # ========================================================
    # DATE AND SCOPE FILTERING
    # ========================================================

    def _apply_date_range(
        self,
        dataframe: pd.DataFrame,
        plan: HeadcountQueryPlan,
    ) -> pd.DataFrame:
        result = dataframe.copy()

        if plan.date_range is None:
            latest_date = result[
                "activity_date"
            ].max()

            return result[
                result["activity_date"].eq(
                    latest_date
                )
            ].copy()

        if plan.date_range.start_date is not None:
            result = result[
                result["activity_date"]
                >= pd.Timestamp(
                    plan.date_range.start_date
                )
            ]

        if plan.date_range.end_date is not None:
            result = result[
                result["activity_date"]
                <= pd.Timestamp(
                    plan.date_range.end_date
                )
            ]

        return result

    def _apply_scope(
        self,
        dataframe: pd.DataFrame,
        plan: HeadcountQueryPlan,
    ) -> tuple[pd.DataFrame, dict[str, Any]]:
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
            result = self._filter_name(
                result,
                column="department",
                id_column="department_id",
                requested_value=requested_department,
                label="department",
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
            result = self._filter_name(
                result,
                column="business_unit",
                id_column=None,
                requested_value=requested_business_unit,
                label="business unit",
            )

            resolved_scope["business_unit"] = (
                result["business_unit"].iloc[0]
            )

        if result.empty:
            raise HeadcountDailyScopeNotFoundError(
                "No daily workforce activity was found for "
                "the requested scope."
            )

        return result, resolved_scope

    @staticmethod
    def _filter_name(
        dataframe: pd.DataFrame,
        *,
        column: str,
        id_column: str | None,
        requested_value: str,
        label: str,
    ) -> pd.DataFrame:
        normalized = (
            requested_value.strip().casefold()
        )

        values = (
            dataframe[column]
            .astype("string")
            .str.strip()
            .str.casefold()
        )

        exact_mask = values.eq(normalized)

        if id_column is not None:
            id_values = (
                dataframe[id_column]
                .astype("string")
                .str.strip()
                .str.casefold()
            )

            exact_mask = (
                exact_mask
                | id_values.eq(normalized)
            )

        exact = dataframe[exact_mask]

        if not exact.empty:
            return exact.copy()

        partial = dataframe[
            values.str.contains(
                re.escape(normalized),
                regex=True,
                na=False,
            )
        ]

        unique_names = partial[
            column
        ].dropna().unique()

        if len(unique_names) == 1:
            return partial.copy()

        raise HeadcountDailyScopeNotFoundError(
            f"The requested {label} "
            f"{requested_value!r} was not found uniquely."
        )

    @staticmethod
    def _find_name_in_question(
        *,
        question: str,
        values: pd.Series,
    ) -> str | None:
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
        *,
        group_by: str | None,
    ) -> pd.DataFrame:
        if group_by == "activity_date":
            return self._aggregate_by_date(
                dataframe
            )

        if group_by == "department":
            identity_columns = [
                "department_id",
                "department",
                "business_unit",
            ]

            return self._aggregate_period_scope(
                dataframe,
                identity_columns,
            )

        if group_by == "business_unit":
            return self._aggregate_period_scope(
                dataframe,
                ["business_unit"],
            )

        result = self._aggregate_period_scope(
            dataframe.assign(
                organization="All"
            ),
            ["organization"],
        )

        return result

    def _aggregate_by_date(
        self,
        dataframe: pd.DataFrame,
    ) -> pd.DataFrame:
        summable_columns = [
            *DAILY_FLOW_METRICS,
            *DAILY_STOCK_METRICS,
        ]

        result = (
            dataframe
            .groupby(
                "activity_date",
                dropna=False,
            )[summable_columns]
            .sum()
            .reset_index()
        )

        return self._add_availability_percentage(
            result,
            denominator_column="actual_employee_count",
        )

    def _aggregate_period_scope(
        self,
        dataframe: pd.DataFrame,
        identity_columns: list[str],
    ) -> pd.DataFrame:
        latest_date = dataframe[
            "activity_date"
        ].max()

        latest = dataframe[
            dataframe["activity_date"].eq(
                latest_date
            )
        ]

        latest_stock = (
            latest
            .groupby(
                identity_columns,
                dropna=False,
            )[list(DAILY_STOCK_METRICS)]
            .sum()
            .reset_index()
        )

        period_flows = (
            dataframe
            .groupby(
                identity_columns,
                dropna=False,
            )[
                [
                    *DAILY_FLOW_METRICS,
                    "actual_employee_count",
                ]
            ]
            .sum()
            .reset_index()
            .rename(
                columns={
                    "actual_employee_count":
                        "employee_day_denominator",
                }
            )
        )

        result = latest_stock.merge(
            period_flows,
            on=identity_columns,
            how="outer",
        )

        return self._add_availability_percentage(
            result,
            denominator_column="employee_day_denominator",
        )

    @staticmethod
    def _add_availability_percentage(
        dataframe: pd.DataFrame,
        *,
        denominator_column: str,
    ) -> pd.DataFrame:
        result = dataframe.copy()

        denominator = result[
            denominator_column
        ].replace(0, pd.NA)

        result[
            "workforce_availability_percentage"
        ] = (
            (
                result["employees_available_for_work"]
                / denominator
            )
            * 100
        ).round(2).fillna(0.0)

        return result

    @staticmethod
    def _sort_and_limit(
        *,
        dataframe: pd.DataFrame,
        plan: HeadcountQueryPlan,
    ) -> pd.DataFrame:
        result = dataframe.copy()

        if (
            plan.sort_by is not None
            and plan.sort_by in result.columns
        ):
            result = result.sort_values(
                plan.sort_by,
                ascending=(
                    plan.sort_direction
                    == SortDirection.ASCENDING
                ),
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
        row: pd.Series,
        metrics: list[str],
    ) -> list[HeadcountMetricResult]:
        results: list[HeadcountMetricResult] = []

        for metric_name in metrics:
            if metric_name not in row.index:
                continue

            definition = METRICS[
                metric_name
            ]

            numerator: int | float | None = None
            denominator: int | float | None = None

            if (
                metric_name
                == "workforce_availability_percentage"
            ):
                numerator = self._number_value(
                    row["employees_available_for_work"]
                )

                denominator_column = (
                    "employee_day_denominator"
                    if "employee_day_denominator"
                    in row.index
                    else "actual_employee_count"
                )

                denominator = self._number_value(
                    row[denominator_column]
                )

            results.append(
                HeadcountMetricResult(
                    metric_name=metric_name,
                    display_name=definition.display_name,
                    value=self._clean_value(
                        row[metric_name]
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
        if group_by == "activity_date":
            identity_columns = [
                "activity_date",
            ]

        elif group_by == "department":
            identity_columns = [
                "department_id",
                "department",
                "business_unit",
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

        records: list[dict[str, Any]] = []

        for record in dataframe[
            selected_columns
        ].to_dict(orient="records"):
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
            HeadcountDailyService
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
    def _activity_as_of_date(
        dataframe: pd.DataFrame,
    ) -> date | None:
        value = dataframe[
            "activity_date"
        ].max()

        if pd.isna(value):
            return None

        return pd.Timestamp(value).date()

    def _organization_as_of_date(
        self,
    ) -> date | None:
        value = self.repository.get_data_as_of_date()

        if value is None:
            return None

        try:
            return date.fromisoformat(value)
        except ValueError:
            return None