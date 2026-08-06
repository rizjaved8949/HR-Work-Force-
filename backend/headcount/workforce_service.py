"""Deterministic workforce-composition analysis.

This service uses Employee_Profile.csv and supporting master tables to
answer workforce composition questions by job level, employment type,
status, work mode, location, employee category, inclusion category,
shift, career level, organizational unit, and cost center.

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


class HeadcountWorkforceError(RuntimeError):
    """Base error for workforce-composition analysis."""


class HeadcountWorkforceNotFoundError(
    HeadcountWorkforceError
):
    """Raised when no employee records match the requested scope."""


WORKFORCE_COMPOSITION_METRICS: Final[set[str]] = {
    "actual_employee_count",
    "included_in_approved_headcount_count",
    "excluded_from_approved_headcount_count",
    "approved_headcount_inclusion_percentage",
    "average_tenure_months",
    "average_years_in_company",
}


WORKFORCE_COMPOSITION_ONLY_METRICS: Final[set[str]] = {
    "included_in_approved_headcount_count",
    "excluded_from_approved_headcount_count",
    "approved_headcount_inclusion_percentage",
    "average_tenure_months",
    "average_years_in_company",
}


WORKFORCE_GROUPING_DIMENSIONS: Final[set[str]] = {
    "department",
    "business_unit",
    "organizational_unit",
    "work_location",
    "cost_center",
    "job_level",
    "career_level",
    "employment_type",
    "employee_status",
    "work_mode",
    "shift_type",
    "employee_category",
    "headcount_inclusion_category",
    "included_in_approved_headcount",
}


WORKFORCE_SPECIFIC_GROUPINGS: Final[set[str]] = {
    "organizational_unit",
    "work_location",
    "cost_center",
    "job_level",
    "career_level",
    "employment_type",
    "employee_status",
    "work_mode",
    "shift_type",
    "employee_category",
    "headcount_inclusion_category",
    "included_in_approved_headcount",
}


WORKFORCE_FILTER_COLUMN_MAP: Final[dict[str, str]] = {
    "department": "department",
    "business_unit": "business_unit",
    "organizational_unit": "organizational_unit_name",
    "work_location": "work_location_name",
    "cost_center": "cost_center_name",
    "job_level": "job_level",
    "career_level": "career_level",
    "employment_type": "employment_type",
    "employee_status": "employee_status",
    "work_mode": "work_mode",
    "shift_type": "shift_type",
    "employee_category": "employee_category",
    "headcount_inclusion_category": (
        "headcount_inclusion_category"
    ),
    "included_in_approved_headcount": (
        "included_in_approved_headcount"
    ),
}


QUESTION_VALUE_ALIASES: Final[
    dict[str, dict[str, str]]
] = {
    "job_level": {
        "lead/manager": "Lead/Manager",
        "lead manager": "Lead/Manager",
        "managers": "Lead/Manager",
        "manager level": "Lead/Manager",
        "executives": "Executive",
        "executive employees": "Executive",
        "senior employees": "Senior",
        "seniors": "Senior",
        "senior level": "Senior",
        "mid level": "Mid",
        "mid-level": "Mid",
        "junior employees": "Junior",
        "juniors": "Junior",
        "junior level": "Junior",
        "intern level": "Intern",
    },
    "career_level": {
        "senior professionals": "Senior Professional",
        "senior professional": "Senior Professional",
        "entry level": "Entry Level",
        "entry-level": "Entry Level",
        "professional level": "Professional",
        "management level": "Management",
        "internship career level": "Internship",
        "executive career level": "Executive",
    },
    "employment_type": {
        "permanent employees": "Permanent",
        "permanent staff": "Permanent",
        "permanent workforce": "Permanent",
        "contract employees": "Contract",
        "contract staff": "Contract",
        "contract workforce": "Contract",
        "internship employees": "Internship",
        "internship staff": "Internship",
        "interns": "Internship",
    },
    "employee_status": {
        "employees on probation": "Probation",
        "probation employees": "Probation",
        "probationary employees": "Probation",
        "active employees": "Active",
        "active staff": "Active",
    },
    "work_mode": {
        "on-site employees": "On-site",
        "onsite employees": "On-site",
        "on site employees": "On-site",
        "hybrid employees": "Hybrid",
        "hybrid staff": "Hybrid",
        "remote employees": "Remote",
        "remote staff": "Remote",
    },
    "shift_type": {
        "day shift": "Day",
        "night shift": "Night",
        "evening shift": "Evening",
        "rotational shift": "Rotational",
    },
    "employee_category": {
        "regular employees": "Regular Employee",
        "regular employee": "Regular Employee",
        "contract category": "Contract Employee",
        "contract employee category": "Contract Employee",
        "intern category": "Intern",
    },
    "headcount_inclusion_category": {
        "regular headcount": "Regular Headcount",
        "contract headcount": "Contract Headcount",
        "internship headcount": "Internship Headcount",
    },
    "included_in_approved_headcount": {
        "included in approved headcount": "Yes",
        "inside approved headcount": "Yes",
        "excluded from approved headcount": "No",
        "outside approved headcount": "No",
        "not included in approved headcount": "No",
    },
}


COMPOSITION_QUESTION_TERMS: Final[tuple[str, ...]] = (
    "job level",
    "career level",
    "employment type",
    "employee status",
    "work mode",
    "shift type",
    "employee category",
    "headcount inclusion",
    "approved headcount",
    "work location",
    "cost center",
    "cost centre",
    "organizational unit",
    "org unit",
    "permanent employees",
    "contract employees",
    "employees on probation",
    "remote employees",
    "hybrid employees",
    "on-site employees",
    "onsite employees",
    "senior employees",
    "junior employees",
)


def should_use_workforce_service(
    plan: HeadcountQueryPlan,
) -> bool:
    """Return whether a plan requires workforce-composition data."""

    if any(
        metric in WORKFORCE_COMPOSITION_ONLY_METRICS
        for metric in plan.metrics
    ):
        return True

    if any(
        dimension in WORKFORCE_SPECIFIC_GROUPINGS
        for dimension in plan.group_by
    ):
        return True

    if any(
        filter_item.field in WORKFORCE_FILTER_COLUMN_MAP
        for filter_item in plan.filters
    ):
        return True

    scope = plan.scope

    scope_values = (
        scope.organizational_unit,
        scope.work_location,
        scope.job_level,
        scope.employment_type,
        scope.employee_status,
        scope.work_mode,
        getattr(scope, "cost_center", None),
        getattr(scope, "career_level", None),
        getattr(scope, "shift_type", None),
        getattr(scope, "employee_category", None),
        getattr(scope, "headcount_inclusion_category", None),
        getattr(scope, "included_in_approved_headcount", None),
    )

    if any(value is not None for value in scope_values):
        return True

    question = plan.question.casefold()

    return any(
        term in question
        for term in COMPOSITION_QUESTION_TERMS
    )


class HeadcountWorkforceService:
    """Execute deterministic workforce-composition queries."""

    def __init__(
        self,
        repository: HeadcountRepository,
    ) -> None:
        self.repository = repository

    def execute(
        self,
        plan: HeadcountQueryPlan,
    ) -> HeadcountToolResult:
        """Execute one workforce-composition query."""

        unsupported_metrics = [
            metric
            for metric in plan.metrics
            if metric not in WORKFORCE_COMPOSITION_METRICS
        ]

        if unsupported_metrics:
            return HeadcountToolResult(
                status=HeadcountResultStatus.UNSUPPORTED,
                question=plan.question,
                analysis_type=plan.analysis_type,
                message=(
                    "Some requested metrics are not supported "
                    "by the workforce-composition service."
                ),
                limitations=[
                    (
                        "Unsupported workforce metrics: "
                        + ", ".join(unsupported_metrics)
                    )
                ],
                data_as_of_date=self._organization_as_of_date(),
            )

        unsupported_grouping = [
            dimension
            for dimension in plan.group_by
            if dimension not in WORKFORCE_GROUPING_DIMENSIONS
        ]

        if unsupported_grouping:
            return HeadcountToolResult(
                status=HeadcountResultStatus.UNSUPPORTED,
                question=plan.question,
                analysis_type=plan.analysis_type,
                message=(
                    "Some requested workforce grouping dimensions "
                    "are not supported."
                ),
                limitations=[
                    (
                        "Unsupported workforce grouping: "
                        + ", ".join(unsupported_grouping)
                    )
                ],
                data_as_of_date=self._organization_as_of_date(),
            )

        if len(plan.group_by) > 2:
            return HeadcountToolResult(
                status=HeadcountResultStatus.UNSUPPORTED,
                question=plan.question,
                analysis_type=plan.analysis_type,
                message=(
                    "Workforce composition currently supports up "
                    "to two grouping dimensions at a time."
                ),
                data_as_of_date=self._organization_as_of_date(),
            )

        try:
            workforce = self._prepare_workforce()

            workforce, resolved_scope = self._apply_scope(
                workforce,
                plan,
            )

            workforce = self._apply_question_filters(
                workforce,
                plan.question,
            )

            workforce = self._apply_structured_filters(
                workforce,
                plan.filters,
            )

            if workforce.empty:
                raise HeadcountWorkforceNotFoundError(
                    "No employee records matched the requested "
                    "workforce scope and conditions."
                )

            requested_metrics = (
                plan.metrics
                if plan.metrics
                else ["actual_employee_count"]
            )

            summary = self._calculate_metrics(
                workforce
            )

            metric_results = self._create_metric_results(
                summary,
                requested_metrics,
            )

            result_frame = self._group_workforce(
                workforce,
                group_by=plan.group_by,
            )

            result_frame = self._sort_and_limit(
                dataframe=result_frame,
                plan=plan,
            )

            records = (
                self._create_records(
                    result_frame,
                    requested_metrics,
                    plan.group_by,
                )
                if plan.include_details
                else []
            )

            resolved_scope["group_by"] = (
                plan.group_by
                if plan.group_by
                else ["organization"]
            )

            return HeadcountToolResult(
                status=HeadcountResultStatus.SUCCESS,
                question=plan.question,
                analysis_type=plan.analysis_type,
                message=(
                    "Workforce-composition analysis completed "
                    "successfully."
                ),
                resolved_scope=resolved_scope,
                metrics=metric_results,
                records=records,
                evidence_sources=[
                    "Employee_Profile.csv",
                    "Work_Location_Master.csv",
                    "Organizational_Unit_Master.csv",
                    "Cost_Center_Master.csv",
                ],
                data_as_of_date=self._workforce_as_of_date(
                    workforce
                ),
                calculation_notes=[
                    (
                        "Employee counts use distinct Employee_ID "
                        "values from the current employee profile."
                    ),
                    (
                        "Onsite and On-site values are normalized "
                        "to the single label On-site."
                    ),
                    (
                        "Approved-headcount inclusion percentage "
                        "equals included employees divided by all "
                        "matched employees."
                    ),
                ],
            )

        except HeadcountWorkforceNotFoundError as error:
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
                    "Workforce-composition analysis could not "
                    "be completed."
                ),
                limitations=[str(error)],
                data_as_of_date=self._organization_as_of_date(),
            )

    # ========================================================
    # DATA PREPARATION
    # ========================================================

    def _prepare_workforce(self) -> pd.DataFrame:
        employees = self.repository.get_table(
            "employees"
        ).copy()

        locations = self.repository.get_table(
            "work_locations"
        )

        organizational_units = self.repository.get_table(
            "organizational_units"
        )

        cost_centers = self.repository.get_table(
            "cost_centers"
        )

        employees = employees.rename(
            columns={
                "Employee_ID": "employee_id",
                "Employee_Name": "employee_name",
                "Department_ID": "department_id",
                "Department": "department",
                "Business_Unit": "business_unit",
                "Organizational_Unit_ID": (
                    "organizational_unit_id"
                ),
                "Work_Location_ID": "work_location_id",
                "Cost_Center_ID": "cost_center_id",
                "Position_ID": "position_id",
                "Position_Title": "position_title",
                "Designation": "designation",
                "Job_Level": "job_level",
                "Career_Level": "career_level",
                "Employment_Type": "employment_type",
                "Employee_Status": "employee_status",
                "Work_Mode": "work_mode",
                "Shift_Type": "shift_type",
                "Employee_Category": "employee_category",
                "Headcount_Inclusion_Category": (
                    "headcount_inclusion_category"
                ),
                "Included_in_Approved_Headcount": (
                    "included_in_approved_headcount"
                ),
                "Tenure_Months": "tenure_months",
                "Years_in_Company": "years_in_company",
                "Standard_Weekly_Hours": (
                    "standard_weekly_hours"
                ),
                "Hire_Date": "hire_date",
                "Data_As_Of_Date": "data_as_of_date",
            }
        )

        employees["hire_date"] = pd.to_datetime(
            employees["hire_date"],
            errors="coerce",
        )

        employees["data_as_of_date"] = pd.to_datetime(
            employees["data_as_of_date"],
            errors="coerce",
        )

        numeric_columns = [
            "tenure_months",
            "years_in_company",
            "standard_weekly_hours",
        ]

        for column in numeric_columns:
            employees[column] = pd.to_numeric(
                employees[column],
                errors="coerce",
            )

        employees["work_mode"] = (
            employees["work_mode"]
            .astype("string")
            .str.strip()
            .replace(
                {
                    "Onsite": "On-site",
                    "On Site": "On-site",
                    "On-site": "On-site",
                }
            )
        )

        location_reference = locations[
            [
                "Work_Location_ID",
                "Work_Location_Name",
                "Work_Location_Type",
                "City",
                "Region",
            ]
        ].drop_duplicates(
            subset=["Work_Location_ID"]
        ).rename(
            columns={
                "Work_Location_ID": "work_location_id",
                "Work_Location_Name": "work_location_name",
                "Work_Location_Type": "work_location_type",
                "City": "city",
                "Region": "region",
            }
        )

        organizational_unit_reference = organizational_units[
            [
                "Organizational_Unit_ID",
                "Organizational_Unit_Name",
                "Organizational_Unit_Type",
            ]
        ].drop_duplicates(
            subset=["Organizational_Unit_ID"]
        ).rename(
            columns={
                "Organizational_Unit_ID": (
                    "organizational_unit_id"
                ),
                "Organizational_Unit_Name": (
                    "organizational_unit_name"
                ),
                "Organizational_Unit_Type": (
                    "organizational_unit_type"
                ),
            }
        )

        cost_center_reference = cost_centers[
            [
                "Cost_Center_ID",
                "Cost_Center_Name",
            ]
        ].drop_duplicates(
            subset=["Cost_Center_ID"]
        ).rename(
            columns={
                "Cost_Center_ID": "cost_center_id",
                "Cost_Center_Name": "cost_center_name",
            }
        )

        employees = employees.merge(
            location_reference,
            on="work_location_id",
            how="left",
        )

        employees = employees.merge(
            organizational_unit_reference,
            on="organizational_unit_id",
            how="left",
        )

        employees = employees.merge(
            cost_center_reference,
            on="cost_center_id",
            how="left",
        )

        return employees

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

        scope_specs: list[
            tuple[str, str | None, str | None, str]
        ] = [
            (
                "department",
                "department_id",
                plan.scope.department,
                "department",
            ),
            (
                "business_unit",
                None,
                plan.scope.business_unit,
                "business unit",
            ),
            (
                "organizational_unit_name",
                "organizational_unit_id",
                plan.scope.organizational_unit,
                "organizational unit",
            ),
            (
                "work_location_name",
                "work_location_id",
                plan.scope.work_location,
                "work location",
            ),
            (
                "cost_center_name",
                "cost_center_id",
                getattr(plan.scope, "cost_center", None),
                "cost center",
            ),
            (
                "job_level",
                None,
                plan.scope.job_level,
                "job level",
            ),
            (
                "career_level",
                None,
                getattr(plan.scope, "career_level", None),
                "career level",
            ),
            (
                "employment_type",
                None,
                plan.scope.employment_type,
                "employment type",
            ),
            (
                "employee_status",
                None,
                plan.scope.employee_status,
                "employee status",
            ),
            (
                "work_mode",
                None,
                plan.scope.work_mode,
                "work mode",
            ),
            (
                "shift_type",
                None,
                getattr(plan.scope, "shift_type", None),
                "shift type",
            ),
            (
                "employee_category",
                None,
                getattr(plan.scope, "employee_category", None),
                "employee category",
            ),
            (
                "headcount_inclusion_category",
                None,
                getattr(
                    plan.scope,
                    "headcount_inclusion_category",
                    None,
                ),
                "headcount inclusion category",
            ),
            (
                "included_in_approved_headcount",
                None,
                getattr(
                    plan.scope,
                    "included_in_approved_headcount",
                    None,
                ),
                "approved Headcount inclusion",
            ),
        ]

        for (
            name_column,
            id_column,
            requested_value,
            label,
        ) in scope_specs:
            if requested_value is None:
                continue

            result = self._filter_named_value(
                result,
                name_column=name_column,
                id_column=id_column,
                requested_value=requested_value,
                label=label,
            )

            resolved_scope[label.replace(" ", "_")] = (
                str(requested_value)
            )

        return result, resolved_scope

    def _apply_question_filters(
        self,
        dataframe: pd.DataFrame,
        question: str,
    ) -> pd.DataFrame:
        result = dataframe.copy()
        normalized_question = question.casefold()

        for column, alias_map in QUESTION_VALUE_ALIASES.items():
            matched_value: str | None = None

            for phrase, canonical_value in sorted(
                alias_map.items(),
                key=lambda item: len(item[0]),
                reverse=True,
            ):
                pattern = (
                    rf"(?<!\w)"
                    rf"{re.escape(phrase.casefold())}"
                    rf"(?!\w)"
                )

                if re.search(pattern, normalized_question):
                    matched_value = canonical_value
                    break

            if matched_value is None:
                continue

            result = self._filter_named_value(
                result,
                name_column=column,
                id_column=None,
                requested_value=matched_value,
                label=column.replace("_", " "),
            )

        return result

    def _apply_structured_filters(
        self,
        dataframe: pd.DataFrame,
        filters: list[HeadcountFilter],
    ) -> pd.DataFrame:
        result = dataframe.copy()

        for filter_item in filters:
            column = WORKFORCE_FILTER_COLUMN_MAP.get(
                filter_item.field
            )

            if column is None or column not in result.columns:
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
        values = dataframe[column]
        operator = filter_item.operator
        expected: Any = filter_item.value

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
                    raise HeadcountWorkforceError(
                        f"The between filter for "
                        f"{filter_item.field!r} requires "
                        "exactly two numeric values."
                    )

                lower = HeadcountWorkforceService._to_float(
                    expected[0],
                    filter_item.field,
                )

                upper = HeadcountWorkforceService._to_float(
                    expected[1],
                    filter_item.field,
                )

                return dataframe[
                    numeric_values.between(
                        lower,
                        upper,
                        inclusive="both",
                    )
                ]

            numeric_expected = (
                HeadcountWorkforceService._to_float(
                    expected,
                    filter_item.field,
                )
            )

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
            values.astype("string")
            .str.strip()
        )

        if not filter_item.case_sensitive:
            text_values = text_values.str.casefold()

        def normalize_text(value: Any) -> str:
            normalized = str(value).strip()

            return (
                normalized
                if filter_item.case_sensitive
                else normalized.casefold()
            )

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
            expected_values = (
                expected
                if isinstance(expected, list)
                else [expected]
            )

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

        raise HeadcountWorkforceError(
            f"Unsupported filter operator "
            f"{operator.value!r} for field "
            f"{filter_item.field!r}."
        )

    @staticmethod
    def _to_float(
        value: Any,
        field_name: str,
    ) -> float:
        if (
            value is None
            or isinstance(value, (bool, date, list))
        ):
            raise HeadcountWorkforceError(
                f"A valid numeric value is required for "
                f"filter field {field_name!r}."
            )

        try:
            return float(value)
        except (TypeError, ValueError) as error:
            raise HeadcountWorkforceError(
                f"Invalid numeric value {value!r} for "
                f"filter field {field_name!r}."
            ) from error

    @staticmethod
    def _filter_named_value(
        dataframe: pd.DataFrame,
        *,
        name_column: str,
        id_column: str | None,
        requested_value: str,
        label: str,
    ) -> pd.DataFrame:
        normalized = requested_value.strip().casefold()

        name_values = (
            dataframe[name_column]
            .astype("string")
            .str.strip()
            .str.casefold()
        )

        mask = name_values.eq(normalized)

        if id_column is not None:
            id_values = (
                dataframe[id_column]
                .astype("string")
                .str.strip()
                .str.casefold()
            )

            mask = mask | id_values.eq(normalized)

        exact = dataframe[mask]

        if not exact.empty:
            return exact.copy()

        partial = dataframe[
            name_values.str.contains(
                re.escape(normalized),
                regex=True,
                na=False,
            )
        ]

        unique_names = (
            partial[name_column]
            .dropna()
            .astype("string")
            .drop_duplicates()
        )

        if len(unique_names) == 1:
            return partial.copy()

        raise HeadcountWorkforceNotFoundError(
            f"The requested {label} "
            f"{requested_value!r} was not found uniquely."
        )

    # ========================================================
    # CALCULATIONS AND GROUPING
    # ========================================================

    def _calculate_metrics(
        self,
        dataframe: pd.DataFrame,
    ) -> dict[str, int | float | None]:
        total_count = self._distinct_employee_count(
            dataframe
        )

        included = dataframe[
            dataframe["included_in_approved_headcount"]
            .astype("string")
            .str.casefold()
            .eq("yes")
        ]

        excluded = dataframe[
            dataframe["included_in_approved_headcount"]
            .astype("string")
            .str.casefold()
            .eq("no")
        ]

        included_count = self._distinct_employee_count(
            included
        )

        excluded_count = self._distinct_employee_count(
            excluded
        )

        inclusion_percentage = (
            round(
                included_count / total_count * 100,
                2,
            )
            if total_count
            else 0.0
        )

        tenure_values = pd.to_numeric(
            dataframe["tenure_months"],
            errors="coerce",
        ).dropna()

        years_values = pd.to_numeric(
            dataframe["years_in_company"],
            errors="coerce",
        ).dropna()

        return {
            "actual_employee_count": total_count,
            "included_in_approved_headcount_count": (
                included_count
            ),
            "excluded_from_approved_headcount_count": (
                excluded_count
            ),
            "approved_headcount_inclusion_percentage": (
                inclusion_percentage
            ),
            "average_tenure_months": (
                round(float(tenure_values.mean()), 2)
                if not tenure_values.empty
                else None
            ),
            "average_years_in_company": (
                round(float(years_values.mean()), 2)
                if not years_values.empty
                else None
            ),
        }

    def _group_workforce(
        self,
        dataframe: pd.DataFrame,
        *,
        group_by: list[str],
    ) -> pd.DataFrame:
        if not group_by:
            summary = self._calculate_metrics(
                dataframe
            )

            return pd.DataFrame(
                [
                    {
                        "organization": "All",
                        **summary,
                    }
                ]
            )

        group_columns = [
            self._group_column(dimension)
            for dimension in group_by
        ]

        records: list[dict[str, Any]] = []

        grouper: str | list[str] = (
            group_columns[0]
            if len(group_columns) == 1
            else group_columns
        )

        grouped = dataframe.groupby(
            grouper,
            dropna=False,
        )

        for group_value, group_frame in grouped:
            values = (
                group_value
                if isinstance(group_value, tuple)
                else (group_value,)
            )

            record: dict[str, Any] = {}

            for dimension, value in zip(
                group_by,
                values,
                strict=True,
            ):
                record[dimension] = self._clean_value(
                    value
                )

            record.update(
                self._calculate_metrics(group_frame)
            )

            records.append(record)

        return pd.DataFrame(records)

    @staticmethod
    def _group_column(
        dimension: str,
    ) -> str:
        mapping = {
            "department": "department",
            "business_unit": "business_unit",
            "organizational_unit": (
                "organizational_unit_name"
            ),
            "work_location": "work_location_name",
            "cost_center": "cost_center_name",
            "job_level": "job_level",
            "career_level": "career_level",
            "employment_type": "employment_type",
            "employee_status": "employee_status",
            "work_mode": "work_mode",
            "shift_type": "shift_type",
            "employee_category": "employee_category",
            "headcount_inclusion_category": (
                "headcount_inclusion_category"
            ),
            "included_in_approved_headcount": (
                "included_in_approved_headcount"
            ),
        }

        return mapping[dimension]

    @staticmethod
    def _sort_and_limit(
        *,
        dataframe: pd.DataFrame,
        plan: HeadcountQueryPlan,
    ) -> pd.DataFrame:
        result = dataframe.copy()

        sort_column = (
            plan.sort_by
            if (
                plan.sort_by is not None
                and plan.sort_by in result.columns
            )
            else (
                "actual_employee_count"
                if plan.group_by
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

        if plan.group_by:
            result = result.head(plan.limit)

        return result.reset_index(drop=True)

    def _create_metric_results(
        self,
        summary: dict[str, int | float | None],
        metrics: list[str],
    ) -> list[HeadcountMetricResult]:
        results: list[HeadcountMetricResult] = []

        for metric_name in metrics:
            if metric_name not in summary:
                continue

            definition = METRICS[metric_name]

            numerator: int | float | None = None
            denominator: int | float | None = None

            if (
                metric_name
                == "approved_headcount_inclusion_percentage"
            ):
                numerator = summary[
                    "included_in_approved_headcount_count"
                ]

                denominator = summary[
                    "actual_employee_count"
                ]

            results.append(
                HeadcountMetricResult(
                    metric_name=metric_name,
                    display_name=definition.display_name,
                    value=summary[metric_name],
                    unit=definition.unit,
                    numerator=numerator,
                    denominator=denominator,
                )
            )

        return results

    def _create_records(
        self,
        dataframe: pd.DataFrame,
        metrics: list[str],
        group_by: list[str],
    ) -> list[dict[str, Any]]:
        identity_columns = (
            group_by
            if group_by
            else ["organization"]
        )

        selected_columns = [
            column
            for column in (
                identity_columns + metrics
            )
            if column in dataframe.columns
        ]

        records: list[dict[str, Any]] = []

        raw_records = dataframe[
            selected_columns
        ].to_dict(orient="records")

        for record in raw_records:
            records.append(
                {
                    str(key): self._clean_value(value)
                    for key, value in record.items()
                }
            )

        return records

    @staticmethod
    def _distinct_employee_count(
        dataframe: pd.DataFrame,
    ) -> int:
        values = (
            dataframe["employee_id"]
            .dropna()
            .astype("string")
            .drop_duplicates()
        )

        return int(len(values))

    # ========================================================
    # HELPERS
    # ========================================================

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
    def _workforce_as_of_date(
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
