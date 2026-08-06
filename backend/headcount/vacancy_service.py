"""Deterministic detailed vacancy analysis.

This service uses Position_Vacancy_History.csv and Position_Master.csv
to answer detailed vacancy, recruitment-stage, ageing, funding, and
time-to-fill questions.

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
    FilterOperator,
    HeadcountFilter,
    HeadcountMetricResult,
    HeadcountQueryPlan,
    HeadcountResultStatus,
    HeadcountToolResult,
    SortDirection,
)


class HeadcountVacancyError(RuntimeError):
    """Base error for detailed vacancy analysis."""


class HeadcountVacancyNotFoundError(
    HeadcountVacancyError
):
    """Raised when no vacancy matches the requested conditions."""


VACANCY_SERVICE_METRICS: Final[set[str]] = {
    "approved_position_count",
    "budgeted_position_count",
    "vacant_position_count",
    "frozen_position_count",
    "vacant_approved_position_count",
    "funded_vacant_position_count",
    "unfunded_vacant_position_count",
    "vacancy_rate_percentage",
    "vacancy_age_in_days",
    "average_vacancy_age_in_days",
    "long_open_vacancy_count",
    "critical_open_position_count",
    "overdue_vacancy_count",
    "average_time_to_fill_in_days",
}


VACANCY_DETAIL_ONLY_METRICS: Final[set[str]] = {
    "vacancy_age_in_days",
    "average_vacancy_age_in_days",
    "long_open_vacancy_count",
    "critical_open_position_count",
    "overdue_vacancy_count",
    "average_time_to_fill_in_days",
}


VACANCY_GROUPING_DIMENSIONS: Final[set[str]] = {
    "position",
    "department",
    "business_unit",
    "recruitment_stage",
    "position_criticality",
    "vacancy_status",
}


FILTER_COLUMN_MAP: Final[dict[str, str]] = {
    "department": "department",
    "business_unit": "business_unit",
    "position_criticality": "position_criticality",
    "budgeted_position": "budgeted_position",
    "vacancy_age_in_days": "vacancy_age_in_days",
    "vacancy_status": "vacancy_status",
    "recruitment_stage": "recruitment_stage",
    "position": "position_id",
}


class HeadcountVacancyService:
    """Execute detailed vacancy queries."""

    def __init__(
        self,
        repository: HeadcountRepository,
    ) -> None:
        self.repository = repository

    def execute(
        self,
        plan: HeadcountQueryPlan,
    ) -> HeadcountToolResult:
        """Execute one deterministic vacancy query."""

        unsupported_metrics = [
            metric
            for metric in plan.metrics
            if metric not in VACANCY_SERVICE_METRICS
        ]

        if unsupported_metrics:
            return HeadcountToolResult(
                status=HeadcountResultStatus.UNSUPPORTED,
                question=plan.question,
                analysis_type=plan.analysis_type,
                message=(
                    "Some requested vacancy metrics are not "
                    "supported by the vacancy service."
                ),
                limitations=[
                    (
                        "Unsupported vacancy metrics: "
                        + ", ".join(unsupported_metrics)
                    )
                ],
                data_as_of_date=self._organization_as_of_date(),
            )

        unsupported_grouping = [
            dimension
            for dimension in plan.group_by
            if dimension not in VACANCY_GROUPING_DIMENSIONS
        ]

        if unsupported_grouping:
            return HeadcountToolResult(
                status=HeadcountResultStatus.UNSUPPORTED,
                question=plan.question,
                analysis_type=plan.analysis_type,
                message=(
                    "Detailed vacancies can currently be grouped "
                    "by position, department, business unit, "
                    "recruitment stage, criticality, or status."
                ),
                limitations=[
                    (
                        "Unsupported vacancy grouping: "
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
                    "Only one vacancy grouping dimension is "
                    "supported at a time."
                ),
                data_as_of_date=self._organization_as_of_date(),
            )

        try:
            vacancies = self._prepare_vacancies()
            positions = self._prepare_positions()

            vacancies, resolved_scope = self._apply_scope(
                vacancies,
                plan,
            )

            positions = self._apply_position_scope(
                positions,
                resolved_scope,
            )

            vacancies = self._apply_default_status(
                vacancies,
                plan,
            )

            vacancies = self._apply_question_filters(
                vacancies,
                plan.question,
            )

            vacancies = self._apply_structured_filters(
                vacancies,
                plan.filters,
            )

            vacancies = self._apply_date_range(
                vacancies,
                plan,
            )

            if vacancies.empty:
                raise HeadcountVacancyNotFoundError(
                    "No vacancy records matched the requested "
                    "scope and conditions."
                )

            requested_metrics = (
                plan.metrics
                if plan.metrics
                else [
                    "vacant_position_count",
                    "frozen_position_count",
                    "vacant_approved_position_count",
                    "funded_vacant_position_count",
                    "vacancy_rate_percentage",
                ]
            )

            summary = self._calculate_summary(
                vacancies,
                positions,
            )

            metric_results = self._create_metric_results(
                summary,
                requested_metrics,
            )

            group_dimension = (
                plan.group_by[0]
                if plan.group_by
                else None
            )

            records = (
                self._create_records(
                    vacancies=vacancies,
                    positions=positions,
                    metrics=requested_metrics,
                    group_by=group_dimension,
                    plan=plan,
                )
                if plan.include_details
                else []
            )

            resolved_scope["group_by"] = (
                group_dimension or "vacancy details"
            )

            return HeadcountToolResult(
                status=HeadcountResultStatus.SUCCESS,
                question=plan.question,
                analysis_type=plan.analysis_type,
                message=(
                    "Detailed vacancy analysis completed "
                    "successfully."
                ),
                resolved_scope=resolved_scope,
                metrics=metric_results,
                records=records,
                evidence_sources=[
                    "Position_Vacancy_History.csv",
                    "Position_Master.csv",
                    "Department_Master.csv",
                ],
                data_as_of_date=self._vacancy_as_of_date(
                    vacancies
                ),
                calculation_notes=[
                    (
                        "Current open vacancies include positions "
                        "in active recruitment and frozen positions."
                    ),
                    (
                        "Vacant position count excludes frozen "
                        "positions, while vacant approved position "
                        "count includes them."
                    ),
                    (
                        "Long-open vacancies are currently open "
                        "positions older than 90 days."
                    ),
                    (
                        "Overdue vacancies have target fill dates "
                        "earlier than the reporting date."
                    ),
                ],
            )

        except HeadcountVacancyNotFoundError as error:
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
                    "Detailed vacancy analysis could not "
                    "be completed."
                ),
                limitations=[str(error)],
                data_as_of_date=self._organization_as_of_date(),
            )

    # ========================================================
    # DATA PREPARATION
    # ========================================================

    def _prepare_vacancies(self) -> pd.DataFrame:
        vacancies = self.repository.get_table(
            "vacancy_history"
        ).copy()

        departments = self.repository.get_table(
            "departments"
        )

        vacancies = vacancies.rename(
            columns={
                "Vacancy_Record_ID": "vacancy_record_id",
                "Position_ID": "position_id",
                "Position_Title": "position_title",
                "Department_ID": "department_id",
                "Department_Name": "department",
                "Organizational_Unit_ID":
                    "organizational_unit_id",
                "Vacancy_Start_Date": "vacancy_start_date",
                "Vacancy_End_Date": "vacancy_end_date",
                "Vacancy_Status": "vacancy_status",
                "Vacancy_Age_in_Days":
                    "vacancy_age_in_days",
                "Budgeted_Position": "budgeted_position",
                "Position_Criticality":
                    "position_criticality",
                "Recruitment_Stage": "recruitment_stage",
                "Target_Fill_Date": "target_fill_date",
                "Vacancy_Reason": "vacancy_reason",
                "Expected_Time_to_Fill_in_Days":
                    "expected_time_to_fill_in_days",
                "Actual_Time_to_Fill_in_Days":
                    "actual_time_to_fill_in_days",
                "Data_As_Of_Date": "data_as_of_date",
            }
        )

        date_columns = [
            "vacancy_start_date",
            "vacancy_end_date",
            "target_fill_date",
            "data_as_of_date",
        ]

        for column in date_columns:
            vacancies[column] = pd.to_datetime(
                vacancies[column],
                errors="coerce",
            )

        numeric_columns = [
            "vacancy_age_in_days",
            "expected_time_to_fill_in_days",
            "actual_time_to_fill_in_days",
        ]

        for column in numeric_columns:
            vacancies[column] = pd.to_numeric(
                vacancies[column],
                errors="coerce",
            )

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

        vacancies = vacancies.merge(
            department_reference,
            on="department_id",
            how="left",
        )

        return vacancies

    def _prepare_positions(self) -> pd.DataFrame:
        positions = self.repository.get_table(
            "positions"
        ).copy()

        positions = positions.rename(
            columns={
                "Position_ID": "position_id",
                "Department_ID": "department_id",
                "Department": "department",
                "Business_Unit": "business_unit",
                "Approved_Position": "approved_position",
                "Budgeted_Position": "budgeted_position",
            }
        )

        return positions

    # ========================================================
    # SCOPE AND FILTERING
    # ========================================================

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
                name_column="department",
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
                name_column="business_unit",
                id_column=None,
                requested_value=requested_business_unit,
                label="business unit",
            )

            resolved_scope["business_unit"] = (
                result["business_unit"].iloc[0]
            )

        return result, resolved_scope

    @staticmethod
    def _apply_position_scope(
        positions: pd.DataFrame,
        resolved_scope: dict[str, Any],
    ) -> pd.DataFrame:
        result = positions.copy()

        department = resolved_scope.get(
            "department"
        )

        if department is not None:
            result = result[
                result["department"]
                .astype("string")
                .str.casefold()
                .eq(str(department).casefold())
            ]

        business_unit = resolved_scope.get(
            "business_unit"
        )

        if business_unit is not None:
            result = result[
                result["business_unit"]
                .astype("string")
                .str.casefold()
                .eq(str(business_unit).casefold())
            ]

        return result

    @staticmethod
    def _apply_default_status(
        dataframe: pd.DataFrame,
        plan: HeadcountQueryPlan,
    ) -> pd.DataFrame:
        result = dataframe.copy()
        question = plan.question.casefold()

        has_status_filter = any(
            item.field == "vacancy_status"
            for item in plan.filters
        )

        if has_status_filter:
            return result

        if (
            "average_time_to_fill_in_days"
            in plan.metrics
            or "filled vacancies" in question
            or "completed vacancies" in question
        ):
            return result[
                result["vacancy_status"]
                .astype("string")
                .str.casefold()
                .eq("filled")
            ]

        if (
            "all vacancies" in question
            or "vacancy history" in question
            or "historical vacancies" in question
        ):
            return result

        return result[
            result["vacancy_status"]
            .astype("string")
            .str.casefold()
            .eq("currently open")
        ]

    def _apply_question_filters(
        self,
        dataframe: pd.DataFrame,
        question: str,
    ) -> pd.DataFrame:
        result = dataframe.copy()
        normalized = question.casefold()

        if (
            "unfunded" in normalized
            or "without budget" in normalized
        ):
            result = result[
                result["budgeted_position"]
                .astype("string")
                .str.casefold()
                .eq("no")
            ]

        elif (
            "funded" in normalized
            or "budgeted vacancy" in normalized
        ):
            result = result[
                result["budgeted_position"]
                .astype("string")
                .str.casefold()
                .eq("yes")
            ]

        if (
            "critical" in normalized
            or "high priority" in normalized
            or "high-priority" in normalized
        ):
            result = result[
                result["position_criticality"]
                .astype("string")
                .str.casefold()
                .isin(["high", "critical"])
            ]

        if "frozen" in normalized:
            result = result[
                result["recruitment_stage"]
                .astype("string")
                .str.casefold()
                .eq("position frozen")
            ]

        greater_match = re.search(
            r"(?:older than|more than|over)\s+(\d+)\s+days?",
            normalized,
        )

        if greater_match:
            minimum_age = int(
                greater_match.group(1)
            )

            result = result[
                result["vacancy_age_in_days"]
                > minimum_age
            ]

        at_least_match = re.search(
            r"at least\s+(\d+)\s+days?",
            normalized,
        )

        if at_least_match:
            minimum_age = int(
                at_least_match.group(1)
            )

            result = result[
                result["vacancy_age_in_days"]
                >= minimum_age
            ]

        known_stage = self._find_name_in_question(
            question=question,
            values=dataframe["recruitment_stage"],
        )

        if known_stage is not None:
            result = result[
                result["recruitment_stage"]
                .astype("string")
                .str.casefold()
                .eq(known_stage.casefold())
            ]

        return result

    def _apply_structured_filters(
        self,
        dataframe: pd.DataFrame,
        filters: list[HeadcountFilter],
    ) -> pd.DataFrame:
        result = dataframe.copy()

        for filter_item in filters:
            column = FILTER_COLUMN_MAP.get(
                filter_item.field
            )

            if (
                column is None
                or column not in result.columns
            ):
                continue

            result = self._apply_filter(
                result,
                column=column,
                filter_item=filter_item,
            )

        return result

    @staticmethod
    def _apply_filter(
        dataframe: pd.DataFrame,
        *,
        column: str,
        filter_item: HeadcountFilter,
    ) -> pd.DataFrame:
        """Apply one validated structured vacancy filter."""

        values = dataframe[column]
        operator = filter_item.operator
        expected: Any = filter_item.value

        def to_float(value: Any) -> float:
            """Convert a numeric filter value safely."""

            if value is None:
                raise HeadcountVacancyError(
                    f"A numeric value is required for "
                    f"filter field {filter_item.field!r}."
                )

            if isinstance(value, bool):
                raise HeadcountVacancyError(
                    f"A boolean value cannot be used as a "
                    f"numeric filter for "
                    f"{filter_item.field!r}."
                )

            if isinstance(value, date):
                raise HeadcountVacancyError(
                    f"A date value cannot be used as a "
                    f"numeric filter for "
                    f"{filter_item.field!r}."
                )

            if isinstance(value, list):
                raise HeadcountVacancyError(
                    f"A single numeric value is required for "
                    f"{filter_item.field!r}."
                )

            try:
                return float(value)
            except (TypeError, ValueError) as error:
                raise HeadcountVacancyError(
                    f"Invalid numeric value {value!r} for "
                    f"filter field {filter_item.field!r}."
                ) from error

        def normalize_text(value: Any) -> str:
            """Normalize a text filter value."""

            normalized = str(value).strip()

            if filter_item.case_sensitive:
                return normalized

            return normalized.casefold()

        if operator == FilterOperator.IS_NULL:
            return dataframe[values.isna()]

        if operator == FilterOperator.IS_NOT_NULL:
            return dataframe[values.notna()]

        numeric_operators = {
            FilterOperator.GREATER_THAN,
            FilterOperator.GREATER_THAN_OR_EQUAL,
            FilterOperator.LESS_THAN,
            FilterOperator.LESS_THAN_OR_EQUAL,
            FilterOperator.BETWEEN,
        }

        if operator in numeric_operators:
            numeric_values = pd.to_numeric(
                values,
                errors="coerce",
            )

            if operator == FilterOperator.BETWEEN:
                if (
                    not isinstance(expected, list)
                    or len(expected) != 2
                ):
                    raise HeadcountVacancyError(
                        f"The between filter for "
                        f"{filter_item.field!r} requires "
                        "exactly two numeric values."
                    )

                lower = to_float(expected[0])
                upper = to_float(expected[1])

                return dataframe[
                    numeric_values.between(
                        lower,
                        upper,
                        inclusive="both",
                    )
                ]

            numeric_expected = to_float(expected)

            if operator == FilterOperator.GREATER_THAN:
                return dataframe[
                    numeric_values > numeric_expected
                ]

            if (
                operator
                == FilterOperator.GREATER_THAN_OR_EQUAL
            ):
                return dataframe[
                    numeric_values >= numeric_expected
                ]

            if operator == FilterOperator.LESS_THAN:
                return dataframe[
                    numeric_values < numeric_expected
                ]

            if (
                operator
                == FilterOperator.LESS_THAN_OR_EQUAL
            ):
                return dataframe[
                    numeric_values <= numeric_expected
                ]

        text_values = (
            values
            .astype("string")
            .str.strip()
        )

        if not filter_item.case_sensitive:
            text_values = text_values.str.casefold()

        if operator == FilterOperator.EQUALS:
            return dataframe[
                text_values.eq(
                    normalize_text(expected)
                )
            ]

        if operator == FilterOperator.NOT_EQUALS:
            return dataframe[
                ~text_values.eq(
                    normalize_text(expected)
                )
            ]

        if operator in {
            FilterOperator.IN,
            FilterOperator.NOT_IN,
        }:
            expected_values: list[Any]

            if isinstance(expected, list):
                expected_values = expected
            else:
                expected_values = [expected]

            normalized_expected = [
                normalize_text(value)
                for value in expected_values
            ]

            mask = text_values.isin(
                normalized_expected
            )

            if operator == FilterOperator.IN:
                return dataframe[mask]

            return dataframe[~mask]

        if operator == FilterOperator.CONTAINS:
            return dataframe[
                text_values.str.contains(
                    re.escape(
                        normalize_text(expected)
                    ),
                    regex=True,
                    na=False,
                )
            ]

        raise HeadcountVacancyError(
            f"Unsupported filter operator "
            f"{operator.value!r} for field "
            f"{filter_item.field!r}."
        )

    @staticmethod
    def _apply_date_range(
        dataframe: pd.DataFrame,
        plan: HeadcountQueryPlan,
    ) -> pd.DataFrame:
        result = dataframe.copy()

        if plan.date_range is None:
            return result

        if plan.date_range.start_date is not None:
            result = result[
                result["vacancy_start_date"]
                >= pd.Timestamp(
                    plan.date_range.start_date
                )
            ]

        if plan.date_range.end_date is not None:
            result = result[
                result["vacancy_start_date"]
                <= pd.Timestamp(
                    plan.date_range.end_date
                )
            ]

        return result

    # ========================================================
    # CALCULATIONS
    # ========================================================

    def _calculate_summary(
        self,
        vacancies: pd.DataFrame,
        positions: pd.DataFrame,
    ) -> dict[str, Any]:
        open_mask = (
            vacancies["vacancy_status"]
            .astype("string")
            .str.casefold()
            .eq("currently open")
        )

        filled_mask = (
            vacancies["vacancy_status"]
            .astype("string")
            .str.casefold()
            .eq("filled")
        )

        frozen_mask = (
            open_mask
            &
            vacancies["recruitment_stage"]
            .astype("string")
            .str.casefold()
            .eq("position frozen")
        )

        active_vacant_mask = (
            open_mask & ~frozen_mask
        )

        funded_mask = (
            open_mask
            &
            vacancies["budgeted_position"]
            .astype("string")
            .str.casefold()
            .eq("yes")
        )

        unfunded_mask = (
            open_mask
            &
            vacancies["budgeted_position"]
            .astype("string")
            .str.casefold()
            .eq("no")
        )

        critical_mask = (
            open_mask
            &
            vacancies["position_criticality"]
            .astype("string")
            .str.casefold()
            .isin(["high", "critical"])
        )

        long_open_mask = (
            open_mask
            &
            (
                vacancies["vacancy_age_in_days"]
                > 90
            )
        )

        reporting_date = vacancies[
            "data_as_of_date"
        ].max()

        overdue_mask = (
            open_mask
            &
            vacancies["target_fill_date"].notna()
            &
            (
                vacancies["target_fill_date"]
                < reporting_date
            )
        )

        approved_positions = positions[
            positions["approved_position"]
            .astype("string")
            .str.casefold()
            .eq("yes")
        ]["position_id"].nunique()

        budgeted_positions = positions[
            positions["budgeted_position"]
            .astype("string")
            .str.casefold()
            .eq("yes")
        ]["position_id"].nunique()

        open_count = int(
            vacancies.loc[
                open_mask,
                "position_id",
            ].nunique()
        )

        vacancy_rate = (
            round(
                open_count
                / approved_positions
                * 100,
                2,
            )
            if approved_positions
            else 0.0
        )

        open_age = vacancies.loc[
            open_mask,
            "vacancy_age_in_days",
        ].dropna()

        actual_fill_time = vacancies.loc[
            filled_mask,
            "actual_time_to_fill_in_days",
        ].dropna()

        contextual_age: float | int | None = None

        if vacancies["position_id"].nunique() == 1:
            age_values = vacancies[
                "vacancy_age_in_days"
            ].dropna()

            if not age_values.empty:
                contextual_age = float(
                    age_values.iloc[0]
                )

        return {
            "approved_position_count":
                int(approved_positions),

            "budgeted_position_count":
                int(budgeted_positions),

            "vacant_position_count":
                int(
                    vacancies.loc[
                        active_vacant_mask,
                        "position_id",
                    ].nunique()
                ),

            "frozen_position_count":
                int(
                    vacancies.loc[
                        frozen_mask,
                        "position_id",
                    ].nunique()
                ),

            "vacant_approved_position_count":
                open_count,

            "funded_vacant_position_count":
                int(
                    vacancies.loc[
                        funded_mask,
                        "position_id",
                    ].nunique()
                ),

            "unfunded_vacant_position_count":
                int(
                    vacancies.loc[
                        unfunded_mask,
                        "position_id",
                    ].nunique()
                ),

            "vacancy_rate_percentage":
                vacancy_rate,

            "vacancy_age_in_days":
                contextual_age,

            "average_vacancy_age_in_days":
                (
                    round(
                        float(open_age.mean()),
                        2,
                    )
                    if not open_age.empty
                    else None
                ),

            "long_open_vacancy_count":
                int(
                    vacancies.loc[
                        long_open_mask,
                        "position_id",
                    ].nunique()
                ),

            "critical_open_position_count":
                int(
                    vacancies.loc[
                        critical_mask,
                        "position_id",
                    ].nunique()
                ),

            "overdue_vacancy_count":
                int(
                    vacancies.loc[
                        overdue_mask,
                        "position_id",
                    ].nunique()
                ),

            "average_time_to_fill_in_days":
                (
                    round(
                        float(
                            actual_fill_time.mean()
                        ),
                        2,
                    )
                    if not actual_fill_time.empty
                    else None
                ),
        }

    # ========================================================
    # RESULT RECORDS
    # ========================================================

    def _create_records(
        self,
        *,
        vacancies: pd.DataFrame,
        positions: pd.DataFrame,
        metrics: list[str],
        group_by: str | None,
        plan: HeadcountQueryPlan,
    ) -> list[dict[str, Any]]:
        if group_by == "position":
            return self._vacancy_detail_records(
                vacancies,
                plan,
            )

        if group_by is None:
            return self._vacancy_detail_records(
                vacancies,
                plan,
            )

        group_column_map = {
            "department": "department",
            "business_unit": "business_unit",
            "recruitment_stage": "recruitment_stage",
            "position_criticality":
                "position_criticality",
            "vacancy_status": "vacancy_status",
        }

        group_column = group_column_map[
            group_by
        ]

        records: list[dict[str, Any]] = []

        for group_value, group_frame in (
            vacancies.groupby(
                group_column,
                dropna=False,
            )
        ):
            group_positions = positions

            if group_by == "department":
                group_positions = positions[
                    positions["department"]
                    .astype("string")
                    .eq(str(group_value))
                ]

            elif group_by == "business_unit":
                group_positions = positions[
                    positions["business_unit"]
                    .astype("string")
                    .eq(str(group_value))
                ]

            summary = self._calculate_summary(
                group_frame,
                group_positions,
            )

            record: dict[str, Any] = {
                group_by: self._clean_value(
                    group_value
                ),
            }

            for metric in metrics:
                if metric in summary:
                    record[metric] = self._clean_value(
                        summary[metric]
                    )

            records.append(record)

        result = pd.DataFrame(records)

        sort_column = (
            plan.sort_by
            if (
                plan.sort_by is not None
                and plan.sort_by in result.columns
            )
            else (
                metrics[0]
                if (
                    metrics
                    and metrics[0] in result.columns
                )
                else None
            )
        )

        if sort_column is not None:
            result = result.sort_values(
                sort_column,
                ascending=(
                    plan.sort_direction
                    == SortDirection.ASCENDING
                ),
                na_position="last",
            )

        result = result.head(
            plan.limit
        )

        return self._records_from_frame(
            result
        )

    def _vacancy_detail_records(
        self,
        dataframe: pd.DataFrame,
        plan: HeadcountQueryPlan,
    ) -> list[dict[str, Any]]:
        result = dataframe.copy()

        reporting_date = result[
            "data_as_of_date"
        ].max()

        result["overdue_target_fill"] = (
            result["vacancy_status"]
            .astype("string")
            .str.casefold()
            .eq("currently open")
            &
            result["target_fill_date"].notna()
            &
            (
                result["target_fill_date"]
                < reporting_date
            )
        )

        sort_column = (
            plan.sort_by
            if (
                plan.sort_by is not None
                and plan.sort_by in result.columns
            )
            else "vacancy_age_in_days"
        )

        ascending = (
            plan.sort_direction
            == SortDirection.ASCENDING
        )

        result = result.sort_values(
            [
                sort_column,
                "position_id",
            ],
            ascending=[
                ascending,
                True,
            ],
            na_position="last",
        ).head(plan.limit)

        columns = [
            "vacancy_record_id",
            "position_id",
            "position_title",
            "department_id",
            "department",
            "business_unit",
            "organizational_unit_id",
            "vacancy_status",
            "vacancy_start_date",
            "vacancy_end_date",
            "vacancy_age_in_days",
            "budgeted_position",
            "position_criticality",
            "recruitment_stage",
            "target_fill_date",
            "overdue_target_fill",
            "vacancy_reason",
            "expected_time_to_fill_in_days",
            "actual_time_to_fill_in_days",
        ]

        return self._records_from_frame(
            result[columns]
        )

    def _create_metric_results(
        self,
        summary: dict[str, Any],
        metrics: list[str],
    ) -> list[HeadcountMetricResult]:
        results: list[HeadcountMetricResult] = []

        for metric_name in metrics:
            if metric_name not in summary:
                continue

            definition = METRICS[
                metric_name
            ]

            numerator: int | float | None = None
            denominator: int | float | None = None

            if (
                metric_name
                == "vacancy_rate_percentage"
            ):
                numerator = summary[
                    "vacant_approved_position_count"
                ]

                denominator = summary[
                    "approved_position_count"
                ]

            results.append(
                HeadcountMetricResult(
                    metric_name=metric_name,
                    display_name=definition.display_name,
                    value=self._clean_value(
                        summary[metric_name]
                    ),
                    unit=definition.unit,
                    numerator=numerator,
                    denominator=denominator,
                )
            )

        return results

    # ========================================================
    # COMMON HELPERS
    # ========================================================

    @staticmethod
    def _filter_name(
        dataframe: pd.DataFrame,
        *,
        name_column: str,
        id_column: str | None,
        requested_value: str,
        label: str,
    ) -> pd.DataFrame:
        normalized = (
            requested_value.strip().casefold()
        )

        names = (
            dataframe[name_column]
            .astype("string")
            .str.strip()
            .str.casefold()
        )

        mask = names.eq(normalized)

        if id_column is not None:
            ids = (
                dataframe[id_column]
                .astype("string")
                .str.strip()
                .str.casefold()
            )

            mask = mask | ids.eq(normalized)

        exact = dataframe[mask]

        if not exact.empty:
            return exact.copy()

        partial = dataframe[
            names.str.contains(
                re.escape(normalized),
                regex=True,
                na=False,
            )
        ]

        unique_names = partial[
            name_column
        ].dropna().unique()

        if len(unique_names) == 1:
            return partial.copy()

        raise HeadcountVacancyNotFoundError(
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
    def _vacancy_as_of_date(
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