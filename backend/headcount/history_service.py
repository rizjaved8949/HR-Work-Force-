"""Historical Headcount trends and workforce movements.

This service uses:

- Monthly_Headcount_Snapshot.csv for monthly Headcount trends.
- Workforce_Movement_History.csv for join, leave, promotion,
  and transfer analysis.

It is deterministic and does not call an LLM.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Final

import pandas as pd

from headcount.metric_registry import METRICS
from headcount.repository import HeadcountRepository
from headcount.schemas import (
    HeadcountAnalysisType,
    HeadcountMetricResult,
    HeadcountQueryPlan,
    HeadcountResultStatus,
    HeadcountToolResult,
    SortDirection,
)


class HeadcountHistoryError(RuntimeError):
    """Base error for historical Headcount analysis."""


class HeadcountHistoryScopeNotFoundError(
    HeadcountHistoryError
):
    """Raised when a historical scope cannot be resolved."""


SNAPSHOT_METRIC_COLUMNS: Final[dict[str, str]] = {
    "actual_employee_count":
        "Actual_Employee_Count",

    "actual_full_time_equivalent":
        "Actual_Full_Time_Equivalent",

    "approved_position_count":
        "Approved_Position_Count",

    "budgeted_position_count":
        "Budgeted_Position_Count",

    "vacant_approved_position_count":
        "Vacant_Approved_Position_Count",

    "funded_vacant_position_count":
        "Funded_Vacant_Position_Count",

    "overstaffed_employee_count":
        "Overstaffed_Employee_Count",

    "joiner_count":
        "Employees_Joining_During_Month",

    "leaver_count":
        "Employees_Leaving_During_Month",

    "transfer_in_count":
        "Employees_Transferred_In",

    "transfer_out_count":
        "Employees_Transferred_Out",

    "promotion_count":
        "Employees_Promoted",
}


DERIVED_SNAPSHOT_METRICS: Final[set[str]] = {
    "headcount_variance",
    "net_approved_headcount_gap",
    "net_budgeted_headcount_gap",
    "vacancy_rate_percentage",
    "headcount_utilization_percentage",
    "budget_utilization_percentage",
    "monthly_net_workforce_change",
}


MOVEMENT_METRIC_TYPES: Final[dict[str, str]] = {
    "joiner_count": "Join",
    "leaver_count": "Leave",
    "promotion_count": "Promotion",
    "transfer_count": "Transfer",
    "transfer_in_count": "Transfer",
    "transfer_out_count": "Transfer",
}


HISTORY_METRICS: Final[set[str]] = {
    *SNAPSHOT_METRIC_COLUMNS.keys(),
    *DERIVED_SNAPSHOT_METRICS,
    *MOVEMENT_METRIC_TYPES.keys(),
}


class HeadcountHistoryService:
    """Execute Headcount trend and movement queries."""

    def __init__(
        self,
        repository: HeadcountRepository,
    ) -> None:
        self.repository = repository

    def execute(
        self,
        plan: HeadcountQueryPlan,
    ) -> HeadcountToolResult:
        """Execute a trend or movement query."""

        if (
            plan.analysis_type
            == HeadcountAnalysisType.MOVEMENT
        ):
            return self._execute_movements(plan)

        return self._execute_trend(plan)

    # ========================================================
    # MONTHLY TREND ANALYSIS
    # ========================================================

    def _execute_trend(
        self,
        plan: HeadcountQueryPlan,
    ) -> HeadcountToolResult:
        unsupported_metrics = [
            metric
            for metric in plan.metrics
            if metric not in HISTORY_METRICS
        ]

        if unsupported_metrics:
            return HeadcountToolResult(
                status=HeadcountResultStatus.UNSUPPORTED,
                question=plan.question,
                analysis_type=plan.analysis_type,
                message=(
                    "Some requested historical metrics are "
                    "not currently supported."
                ),
                limitations=[
                    (
                        "Unsupported historical metrics: "
                        + ", ".join(unsupported_metrics)
                    )
                ],
                data_as_of_date=self._organization_as_of_date(),
            )

        unsupported_grouping = [
            dimension
            for dimension in plan.group_by
            if dimension not in {
                "month",
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
                    "Historical trends can be grouped by month, "
                    "department, or business unit."
                ),
                limitations=[
                    (
                        "Unsupported historical grouping: "
                        + ", ".join(unsupported_grouping)
                    )
                ],
                data_as_of_date=self._organization_as_of_date(),
            )

        try:
            snapshots = self._prepare_snapshots()

            snapshots, resolved_scope = self._apply_snapshot_scope(
                snapshots,
                plan,
            )

            snapshots = self._apply_snapshot_date_range(
                snapshots,
                plan,
            )

            if snapshots.empty:
                raise HeadcountHistoryScopeNotFoundError(
                    "No monthly Headcount data was found for "
                    "the requested scope and period."
                )

            requested_metrics = (
                plan.metrics
                if plan.metrics
                else [
                    "actual_employee_count",
                    "approved_position_count",
                    "budgeted_position_count",
                    "vacancy_rate_percentage",
                ]
            )

            group_dimension = (
                plan.group_by[0]
                if plan.group_by
                else "month"
            )

            result_frame = self._aggregate_snapshots(
                snapshots,
                group_by=group_dimension,
            )

            result_frame = self._sort_trend_results(
                result_frame,
                plan,
                group_dimension,
            )

            latest_row = self._latest_summary_row(
                snapshots
            )

            metric_results = self._create_metric_results(
                latest_row,
                requested_metrics,
            )

            records = (
                self._create_records(
                    result_frame,
                    requested_metrics,
                    group_dimension,
                )
                if plan.include_details
                else []
            )

            resolved_scope["group_by"] = group_dimension

            resolved_scope["start_month"] = (
                snapshots["snapshot_month"]
                .min()
                .date()
                .isoformat()
            )

            resolved_scope["end_month"] = (
                snapshots["snapshot_month"]
                .max()
                .date()
                .isoformat()
            )

            return HeadcountToolResult(
                status=HeadcountResultStatus.SUCCESS,
                question=plan.question,
                analysis_type=plan.analysis_type,
                message=(
                    "Historical Headcount analysis completed "
                    "successfully."
                ),
                resolved_scope=resolved_scope,
                metrics=metric_results,
                records=records,
                evidence_sources=[
                    "Monthly_Headcount_Snapshot.csv",
                ],
                data_as_of_date=self._snapshot_as_of_date(
                    snapshots
                ),
                calculation_notes=[
                    (
                        "Stock metrics such as actual and approved "
                        "Headcount are summed across departments "
                        "within each month."
                    ),
                    (
                        "Vacancy rate is recalculated from total "
                        "vacant approved positions divided by total "
                        "approved positions."
                    ),
                    (
                        "Monthly net workforce change equals "
                        "joiners plus transfers in, minus leavers "
                        "and transfers out."
                    ),
                ],
            )

        except HeadcountHistoryScopeNotFoundError as error:
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
                    "Historical Headcount analysis could not "
                    "be completed."
                ),
                limitations=[str(error)],
                data_as_of_date=self._organization_as_of_date(),
            )

    def _prepare_snapshots(self) -> pd.DataFrame:
        snapshots = self.repository.get_table(
            "monthly_snapshots"
        ).copy()

        snapshots = snapshots.rename(
            columns={
                "Snapshot_Month": "snapshot_month",
                "Data_As_Of_Date": "data_as_of_date",
                "Department_ID": "department_id",
                "Department_Name": "department",
                "Business_Unit": "business_unit",
            }
        )

        snapshots["snapshot_month"] = pd.to_datetime(
            snapshots["snapshot_month"],
            errors="coerce",
        )

        snapshots["data_as_of_date"] = pd.to_datetime(
            snapshots["data_as_of_date"],
            errors="coerce",
        )

        for metric_name, source_column in (
            SNAPSHOT_METRIC_COLUMNS.items()
        ):
            snapshots[metric_name] = pd.to_numeric(
                snapshots[source_column],
                errors="coerce",
            ).fillna(0)

        numeric_source_columns = [
            "Approved_Monthly_People_Budget",
            "Budget_Variance_Amount",
        ]

        for column in numeric_source_columns:
            snapshots[column] = pd.to_numeric(
                snapshots[column],
                errors="coerce",
            ).fillna(0)

        return self._add_snapshot_derived_metrics(
            snapshots
        )

    @staticmethod
    def _add_snapshot_derived_metrics(
        dataframe: pd.DataFrame,
    ) -> pd.DataFrame:
        result = dataframe.copy()

        result["headcount_variance"] = (
            result["actual_employee_count"]
            - result["approved_position_count"]
        )

        result["net_approved_headcount_gap"] = (
            result["approved_position_count"]
            - result["actual_employee_count"]
        )

        result["net_budgeted_headcount_gap"] = (
            result["budgeted_position_count"]
            - result["actual_employee_count"]
        )

        approved_positions = result[
            "approved_position_count"
        ].replace(0, pd.NA)

        result["vacancy_rate_percentage"] = (
            (
                result[
                    "vacant_approved_position_count"
                ]
                / approved_positions
            )
            * 100
        ).round(2).fillna(0.0)

        result[
            "headcount_utilization_percentage"
        ] = (
            (
                result["actual_employee_count"]
                / approved_positions
            )
            * 100
        ).round(2).fillna(0.0)

        approved_budget = result[
            "Approved_Monthly_People_Budget"
        ].replace(0, pd.NA)

        actual_budget_cost = (
            result["Approved_Monthly_People_Budget"]
            - result["Budget_Variance_Amount"]
        )

        result["budget_utilization_percentage"] = (
            (
                actual_budget_cost
                / approved_budget
            )
            * 100
        ).round(2).fillna(0.0)

        result["monthly_net_workforce_change"] = (
            result["joiner_count"]
            + result["transfer_in_count"]
            - result["leaver_count"]
            - result["transfer_out_count"]
        )

        return result

    def _aggregate_snapshots(
        self,
        dataframe: pd.DataFrame,
        *,
        group_by: str,
    ) -> pd.DataFrame:
        if group_by == "month":
            grouping_columns = ["snapshot_month"]

        elif group_by == "department":
            grouping_columns = [
                "department_id",
                "department",
                "business_unit",
            ]

        else:
            grouping_columns = ["business_unit"]

        summable_columns = list(
            SNAPSHOT_METRIC_COLUMNS.keys()
        ) + [
            "Approved_Monthly_People_Budget",
            "Budget_Variance_Amount",
        ]

        result = (
            dataframe
            .groupby(
                grouping_columns,
                dropna=False,
            )[summable_columns]
            .sum()
            .reset_index()
        )

        return self._add_snapshot_derived_metrics(
            result
        )

    def _latest_summary_row(
        self,
        dataframe: pd.DataFrame,
    ) -> pd.Series:
        latest_month = dataframe[
            "snapshot_month"
        ].max()

        latest_data = dataframe[
            dataframe["snapshot_month"].eq(
                latest_month
            )
        ]

        summary = self._aggregate_snapshots(
            latest_data,
            group_by="month",
        )

        return summary.iloc[0]

    # ========================================================
    # WORKFORCE MOVEMENTS
    # ========================================================

    def _execute_movements(
        self,
        plan: HeadcountQueryPlan,
    ) -> HeadcountToolResult:
        unsupported_metrics = [
            metric
            for metric in plan.metrics
            if metric not in MOVEMENT_METRIC_TYPES
        ]

        if unsupported_metrics:
            return HeadcountToolResult(
                status=HeadcountResultStatus.UNSUPPORTED,
                question=plan.question,
                analysis_type=plan.analysis_type,
                message=(
                    "Some requested movement metrics are not "
                    "currently supported."
                ),
                limitations=[
                    (
                        "Unsupported movement metrics: "
                        + ", ".join(unsupported_metrics)
                    )
                ],
                data_as_of_date=self._organization_as_of_date(),
            )

        try:
            movements = self._prepare_movements()

            movements = self._apply_movement_date_range(
                movements,
                plan,
            )

            requested_metrics = (
                plan.metrics
                if plan.metrics
                else [
                    "joiner_count",
                    "leaver_count",
                    "promotion_count",
                    "transfer_count",
                ]
            )

            resolved_scope: dict[str, Any] = {
                "organization": "All",
            }

            if plan.scope.department is not None:
                resolved_scope["department"] = (
                    plan.scope.department
                )

            metric_results = self._movement_metric_results(
                movements,
                requested_metrics,
                department=plan.scope.department,
            )

            records = self._movement_records(
                movements,
                requested_metrics,
                department=plan.scope.department,
                group_by=(
                    plan.group_by[0]
                    if plan.group_by
                    else None
                ),
                limit=plan.limit,
                sort_direction=plan.sort_direction,
            )

            if plan.date_range is not None:
                resolved_scope["start_date"] = (
                    plan.date_range.start_date
                )

                resolved_scope["end_date"] = (
                    plan.date_range.end_date
                )

            return HeadcountToolResult(
                status=HeadcountResultStatus.SUCCESS,
                question=plan.question,
                analysis_type=plan.analysis_type,
                message=(
                    "Workforce movement analysis completed "
                    "successfully."
                ),
                resolved_scope=resolved_scope,
                metrics=metric_results,
                records=records,
                evidence_sources=[
                    "Workforce_Movement_History.csv",
                ],
                data_as_of_date=self._organization_as_of_date(),
                calculation_notes=[
                    (
                        "Joiners are assigned to their destination "
                        "department."
                    ),
                    (
                        "Leavers are assigned to their originating "
                        "department."
                    ),
                    (
                        "Transfer-in and transfer-out counts are "
                        "kept separate for department analysis."
                    ),
                ],
            )

        except Exception as error:
            return HeadcountToolResult(
                status=HeadcountResultStatus.ERROR,
                question=plan.question,
                analysis_type=plan.analysis_type,
                message=(
                    "Workforce movement analysis could not "
                    "be completed."
                ),
                limitations=[str(error)],
                data_as_of_date=self._organization_as_of_date(),
            )

    def _prepare_movements(self) -> pd.DataFrame:
        movements = self.repository.get_table(
            "movements"
        ).copy()

        movements["Effective_Date"] = pd.to_datetime(
            movements["Effective_Date"],
            errors="coerce",
        )

        return movements

    def _movement_metric_results(
        self,
        dataframe: pd.DataFrame,
        metrics: list[str],
        *,
        department: str | None,
    ) -> list[HeadcountMetricResult]:
        results: list[HeadcountMetricResult] = []

        for metric_name in metrics:
            filtered = self._filter_movement_metric(
                dataframe,
                metric_name,
                department,
            )

            definition = METRICS[metric_name]

            results.append(
                HeadcountMetricResult(
                    metric_name=metric_name,
                    display_name=definition.display_name,
                    value=int(
                        filtered[
                            "Movement_ID"
                        ].nunique()
                    ),
                    unit=definition.unit,
                )
            )

        return results

    def _filter_movement_metric(
        self,
        dataframe: pd.DataFrame,
        metric_name: str,
        department: str | None,
    ) -> pd.DataFrame:
        movement_type = MOVEMENT_METRIC_TYPES[
            metric_name
        ]

        result = dataframe[
            dataframe["Movement_Type"]
            .astype("string")
            .str.casefold()
            .eq(movement_type.casefold())
        ].copy()

        if department is None:
            return result

        normalized_department = (
            department.strip().casefold()
        )

        if metric_name in {
            "joiner_count",
            "promotion_count",
            "transfer_in_count",
        }:
            department_column = (
                "To_Department_Name"
            )

        elif metric_name in {
            "leaver_count",
            "transfer_out_count",
        }:
            department_column = (
                "From_Department_Name"
            )

        else:
            from_match = (
                result["From_Department_Name"]
                .astype("string")
                .str.casefold()
                .eq(normalized_department)
            )

            to_match = (
                result["To_Department_Name"]
                .astype("string")
                .str.casefold()
                .eq(normalized_department)
            )

            return result[
                from_match | to_match
            ]

        return result[
            result[department_column]
            .astype("string")
            .str.casefold()
            .eq(normalized_department)
        ]

    def _movement_records(
        self,
        dataframe: pd.DataFrame,
        metrics: list[str],
        *,
        department: str | None,
        group_by: str | None,
        limit: int,
        sort_direction: SortDirection,
    ) -> list[dict[str, Any]]:
        selected_frames = [
            self._filter_movement_metric(
                dataframe,
                metric,
                department,
            )
            for metric in metrics
        ]

        if not selected_frames:
            return []

        selected = pd.concat(
            selected_frames,
            ignore_index=True,
        ).drop_duplicates(
            subset=["Movement_ID"]
        )

        if group_by == "month":
            selected["month"] = (
                selected["Effective_Date"]
                .dt.to_period("M")
                .dt.to_timestamp()
            )

            grouped = (
                selected
                .groupby(
                    ["month", "Movement_Type"],
                    dropna=False,
                )
                .size()
                .reset_index(name="movement_count")
            )

            grouped = grouped.sort_values(
                "month",
                ascending=True,
            )

            return self._records_from_frame(
                grouped
            )

        ascending = (
            sort_direction
            == SortDirection.ASCENDING
        )

        selected = selected.sort_values(
            "Effective_Date",
            ascending=ascending,
        ).head(limit)

        columns = [
            "Movement_ID",
            "Employee_ID",
            "Employee_Name",
            "Movement_Type",
            "Effective_Date",
            "From_Department_Name",
            "To_Department_Name",
            "From_Position_ID",
            "To_Position_ID",
            "Movement_Reason",
            "Voluntary_Movement",
        ]

        return self._records_from_frame(
            selected[columns]
        )

    # ========================================================
    # FILTERING AND RESULT HELPERS
    # ========================================================

    def _apply_snapshot_scope(
        self,
        dataframe: pd.DataFrame,
        plan: HeadcountQueryPlan,
    ) -> tuple[pd.DataFrame, dict[str, Any]]:
        result = dataframe.copy()

        resolved_scope: dict[str, Any] = {
            "organization": "All",
        }

        if plan.scope.department is not None:
            result = self._filter_name(
                result,
                column="department",
                requested_value=plan.scope.department,
                label="department",
            )

            resolved_scope["department"] = (
                result["department"].iloc[0]
            )

        if plan.scope.business_unit is not None:
            result = self._filter_name(
                result,
                column="business_unit",
                requested_value=plan.scope.business_unit,
                label="business unit",
            )

            resolved_scope["business_unit"] = (
                result["business_unit"].iloc[0]
            )

        return result, resolved_scope

    @staticmethod
    def _filter_name(
        dataframe: pd.DataFrame,
        *,
        column: str,
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

        exact = dataframe[
            values.eq(normalized)
        ]

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

        raise HeadcountHistoryScopeNotFoundError(
            f"The requested {label} "
            f"{requested_value!r} was not found uniquely."
        )

    @staticmethod
    def _apply_snapshot_date_range(
        dataframe: pd.DataFrame,
        plan: HeadcountQueryPlan,
    ) -> pd.DataFrame:
        result = dataframe.copy()

        if plan.date_range is None:
            return result

        if plan.date_range.start_date is not None:
            result = result[
                result["snapshot_month"]
                >= pd.Timestamp(
                    plan.date_range.start_date
                )
            ]

        if plan.date_range.end_date is not None:
            result = result[
                result["snapshot_month"]
                <= pd.Timestamp(
                    plan.date_range.end_date
                )
            ]

        return result

    def _apply_movement_date_range(
        self,
        dataframe: pd.DataFrame,
        plan: HeadcountQueryPlan,
    ) -> pd.DataFrame:
        result = dataframe.copy()

        start_date = (
            plan.date_range.start_date
            if plan.date_range is not None
            else None
        )

        end_date = (
            plan.date_range.end_date
            if plan.date_range is not None
            else self._organization_as_of_date()
        )

        if start_date is not None:
            result = result[
                result["Effective_Date"]
                >= pd.Timestamp(start_date)
            ]

        if end_date is not None:
            result = result[
                result["Effective_Date"]
                <= pd.Timestamp(end_date)
            ]

        return result

    def _sort_trend_results(
        self,
        dataframe: pd.DataFrame,
        plan: HeadcountQueryPlan,
        group_dimension: str,
    ) -> pd.DataFrame:
        result = dataframe.copy()

        if group_dimension == "month":
            return result.sort_values(
                "snapshot_month",
                ascending=True,
            ).reset_index(drop=True)

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
            )

        return result.head(
            plan.limit
        ).reset_index(drop=True)

    def _create_metric_results(
        self,
        row: pd.Series,
        metrics: list[str],
    ) -> list[HeadcountMetricResult]:
        results: list[HeadcountMetricResult] = []

        for metric_name in metrics:
            if metric_name not in row.index:
                continue

            definition = METRICS[metric_name]

            results.append(
                HeadcountMetricResult(
                    metric_name=metric_name,
                    display_name=definition.display_name,
                    value=self._clean_value(
                        row[metric_name]
                    ),
                    unit=definition.unit,
                )
            )

        return results

    def _create_records(
        self,
        dataframe: pd.DataFrame,
        metrics: list[str],
        group_by: str,
    ) -> list[dict[str, Any]]:
        if group_by == "month":
            identity_columns = [
                "snapshot_month",
            ]

        elif group_by == "department":
            identity_columns = [
                "department_id",
                "department",
                "business_unit",
            ]

        else:
            identity_columns = [
                "business_unit",
            ]

        columns = [
            column
            for column in (
                identity_columns + metrics
            )
            if column in dataframe.columns
        ]

        return self._records_from_frame(
            dataframe[columns]
        )

    def _records_from_frame(
        self,
        dataframe: pd.DataFrame,
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []

        for record in dataframe.to_dict(
            orient="records"
        ):
            records.append({
                str(key): self._clean_value(value)
                for key, value in record.items()
            })

        return records

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
    def _snapshot_as_of_date(
        dataframe: pd.DataFrame,
    ) -> date | None:
        value = dataframe[
            "data_as_of_date"
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