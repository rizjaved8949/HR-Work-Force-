"""Headcount exceptions, metric definitions, and rules.

This service reads:

- Headcount_Exception_Register.csv
- Headcount_Management_Metric_Definitions.csv
- Headcount_Management_Rules.csv

It performs deterministic retrieval and counting. It does not call
an LLM or modify Attrition and replacement services.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Final

import pandas as pd

from headcount.metric_registry import (
    METRICS,
    normalize_registry_term,
    resolve_metric_name,
)
from headcount.repository import HeadcountRepository
from headcount.schemas import (
    HeadcountAnalysisType,
    HeadcountMetricResult,
    HeadcountQueryPlan,
    HeadcountResultStatus,
    HeadcountToolResult,
    SortDirection,
)


class HeadcountGovernanceError(RuntimeError):
    """Base error for Headcount governance analysis."""


class HeadcountGovernanceNotFoundError(
    HeadcountGovernanceError
):
    """Raised when no exception, rule, or definition is found."""


GOVERNANCE_METRICS: Final[set[str]] = {
    "open_exception_count",
    "critical_exception_count",
    "warning_exception_count",
    "active_rule_count",
}


class HeadcountGovernanceService:
    """Handle exceptions, metric definitions, and rules."""

    def __init__(
        self,
        repository: HeadcountRepository,
    ) -> None:
        self.repository = repository

    def execute(
        self,
        plan: HeadcountQueryPlan,
    ) -> HeadcountToolResult:
        """Execute one governance-related query."""

        if (
            plan.analysis_type
            == HeadcountAnalysisType.DEFINITION
        ):
            return self._execute_definition(plan)

        if (
            plan.analysis_type
            == HeadcountAnalysisType.RULE
        ):
            return self._execute_rules(plan)

        return self._execute_exceptions(plan)

    # ========================================================
    # EXCEPTIONS
    # ========================================================

    def _execute_exceptions(
        self,
        plan: HeadcountQueryPlan,
    ) -> HeadcountToolResult:
        unsupported_metrics = [
            metric
            for metric in plan.metrics
            if metric not in {
                "open_exception_count",
                "critical_exception_count",
                "warning_exception_count",
            }
        ]

        if unsupported_metrics:
            return HeadcountToolResult(
                status=HeadcountResultStatus.UNSUPPORTED,
                question=plan.question,
                analysis_type=plan.analysis_type,
                message=(
                    "Some requested exception metrics are "
                    "not supported."
                ),
                limitations=[
                    (
                        "Unsupported exception metrics: "
                        + ", ".join(unsupported_metrics)
                    )
                ],
                data_as_of_date=self._organization_as_of_date(),
            )

        unsupported_grouping = [
            dimension
            for dimension in plan.group_by
            if dimension not in {
                "department",
                "severity",
                "exception_type",
            }
        ]

        if unsupported_grouping:
            return HeadcountToolResult(
                status=HeadcountResultStatus.UNSUPPORTED,
                question=plan.question,
                analysis_type=plan.analysis_type,
                message=(
                    "Exceptions can currently be grouped by "
                    "department, severity, or exception type."
                ),
                limitations=[
                    (
                        "Unsupported exception grouping: "
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
                    "Only one exception grouping dimension "
                    "is supported at a time."
                ),
                data_as_of_date=self._organization_as_of_date(),
            )

        try:
            exceptions = self._prepare_exceptions()

            exceptions, resolved_scope = (
                self._apply_exception_scope(
                    exceptions,
                    plan,
                )
            )

            if exceptions.empty:
                raise HeadcountGovernanceNotFoundError(
                    "No Headcount exceptions were found for "
                    "the requested scope."
                )

            requested_metrics = (
                plan.metrics
                if plan.metrics
                else [
                    "open_exception_count",
                ]
            )

            metric_results = (
                self._create_exception_metrics(
                    exceptions,
                    requested_metrics,
                )
            )

            group_dimension = (
                plan.group_by[0]
                if plan.group_by
                else None
            )

            records = (
                self._create_exception_records(
                    exceptions,
                    plan=plan,
                    group_by=group_dimension,
                )
                if plan.include_details
                else []
            )

            resolved_scope["group_by"] = (
                group_dimension or "exception details"
            )

            return HeadcountToolResult(
                status=HeadcountResultStatus.SUCCESS,
                question=plan.question,
                analysis_type=plan.analysis_type,
                message=(
                    "Headcount exception analysis completed "
                    "successfully."
                ),
                resolved_scope=resolved_scope,
                metrics=metric_results,
                records=records,
                evidence_sources=[
                    "Headcount_Exception_Register.csv",
                ],
                data_as_of_date=self._exception_as_of_date(
                    exceptions
                ),
                calculation_notes=[
                    (
                        "Exception counts are based on distinct "
                        "exception IDs."
                    ),
                    (
                        "Open exceptions are filtered using "
                        "Exception_Status equal to Open."
                    ),
                    (
                        "Recommendations are retrieved directly "
                        "from the exception register."
                    ),
                ],
            )

        except HeadcountGovernanceNotFoundError as error:
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
                    "Headcount exception analysis could not "
                    "be completed."
                ),
                limitations=[str(error)],
                data_as_of_date=self._organization_as_of_date(),
            )

    def _prepare_exceptions(self) -> pd.DataFrame:
        exceptions = self.repository.get_table(
            "exceptions"
        ).copy()

        exceptions = exceptions.rename(
            columns={
                "Exception_ID": "exception_id",
                "Department_ID": "department_id",
                "Department_Name": "department",
                "Exception_Type": "exception_type",
                "Severity": "severity",
                "Metric_Name": "metric_name",
                "Current_Value": "current_value",
                "Threshold_Value": "threshold_value",
                "Exception_Description":
                    "exception_description",
                "Recommended_Action":
                    "recommended_action",
                "Detected_Date": "detected_date",
                "Exception_Status": "exception_status",
            }
        )

        exceptions["detected_date"] = pd.to_datetime(
            exceptions["detected_date"],
            errors="coerce",
        )

        return exceptions

    def _apply_exception_scope(
        self,
        dataframe: pd.DataFrame,
        plan: HeadcountQueryPlan,
    ) -> tuple[pd.DataFrame, dict[str, Any]]:
        result = dataframe.copy()

        resolved_scope: dict[str, Any] = {
            "organization": "All",
        }

        question = plan.question.casefold()

        # Current exceptions are the default.
        if "closed" in question:
            result = result[
                result["exception_status"]
                .astype("string")
                .str.casefold()
                .eq("closed")
            ]

            resolved_scope["exception_status"] = "Closed"

        elif "all exception" not in question:
            result = result[
                result["exception_status"]
                .astype("string")
                .str.casefold()
                .eq("open")
            ]

            resolved_scope["exception_status"] = "Open"

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

        if "critical" in question:
            result = result[
                result["severity"]
                .astype("string")
                .str.casefold()
                .eq("critical")
            ]

            resolved_scope["severity"] = "Critical"

        elif "warning" in question:
            result = result[
                result["severity"]
                .astype("string")
                .str.casefold()
                .eq("warning")
            ]

            resolved_scope["severity"] = "Warning"

        known_exception_type = (
            self._find_name_in_question(
                question=plan.question,
                values=dataframe["exception_type"],
            )
        )

        if known_exception_type is not None:
            result = result[
                result["exception_type"]
                .astype("string")
                .str.casefold()
                .eq(
                    known_exception_type.casefold()
                )
            ]

            resolved_scope["exception_type"] = (
                known_exception_type
            )

        return result, resolved_scope

    def _create_exception_metrics(
        self,
        dataframe: pd.DataFrame,
        metrics: list[str],
    ) -> list[HeadcountMetricResult]:
        results: list[HeadcountMetricResult] = []

        metric_values = {
            "open_exception_count": int(
                dataframe[
                    dataframe["exception_status"]
                    .astype("string")
                    .str.casefold()
                    .eq("open")
                ]["exception_id"].nunique()
            ),
            "critical_exception_count": int(
                dataframe[
                    dataframe["severity"]
                    .astype("string")
                    .str.casefold()
                    .eq("critical")
                ]["exception_id"].nunique()
            ),
            "warning_exception_count": int(
                dataframe[
                    dataframe["severity"]
                    .astype("string")
                    .str.casefold()
                    .eq("warning")
                ]["exception_id"].nunique()
            ),
        }

        for metric_name in metrics:
            definition = METRICS[metric_name]

            results.append(
                HeadcountMetricResult(
                    metric_name=metric_name,
                    display_name=definition.display_name,
                    value=metric_values[metric_name],
                    unit=definition.unit,
                )
            )

        return results

    def _create_exception_records(
        self,
        dataframe: pd.DataFrame,
        *,
        plan: HeadcountQueryPlan,
        group_by: str | None,
    ) -> list[dict[str, Any]]:
        if group_by is not None:
            group_column = {
                "department": "department",
                "severity": "severity",
                "exception_type": "exception_type",
            }[group_by]

            grouped = (
                dataframe
                .groupby(
                    group_column,
                    dropna=False,
                )
                .agg(
                    open_exception_count=(
                        "exception_id",
                        "nunique",
                    ),
                    critical_exception_count=(
                        "severity",
                        lambda values: (
                            values.astype("string")
                            .str.casefold()
                            .eq("critical")
                            .sum()
                        ),
                    ),
                    warning_exception_count=(
                        "severity",
                        lambda values: (
                            values.astype("string")
                            .str.casefold()
                            .eq("warning")
                            .sum()
                        ),
                    ),
                )
                .reset_index()
            )

            sort_column = (
                plan.sort_by
                if (
                    plan.sort_by is not None
                    and plan.sort_by in grouped.columns
                )
                else "open_exception_count"
            )

            grouped = grouped.sort_values(
                sort_column,
                ascending=(
                    plan.sort_direction
                    == SortDirection.ASCENDING
                ),
            ).head(plan.limit)

            return self._records_from_frame(grouped)

        result = dataframe.copy()

        severity_rank = {
            "Critical": 1,
            "Warning": 2,
            "Information": 3,
        }

        result["_severity_rank"] = (
            result["severity"]
            .map(severity_rank)
            .fillna(99)
        )

        result = result.sort_values(
            [
                "_severity_rank",
                "exception_id",
            ]
        )

        if "all" not in plan.question.casefold():
            result = result.head(plan.limit)

        columns = [
            "exception_id",
            "department_id",
            "department",
            "exception_type",
            "severity",
            "metric_name",
            "current_value",
            "threshold_value",
            "exception_description",
            "recommended_action",
            "detected_date",
            "exception_status",
        ]

        return self._records_from_frame(
            result[columns]
        )

    # ========================================================
    # METRIC DEFINITIONS
    # ========================================================

    def _execute_definition(
        self,
        plan: HeadcountQueryPlan,
    ) -> HeadcountToolResult:
        try:
            definitions = self.repository.get_table(
                "metric_definitions"
            ).copy()

            definitions["_canonical_metric"] = (
                definitions["Metric_Name"]
                .map(resolve_metric_name)
            )

            requested_metrics = list(
                dict.fromkeys(plan.metrics)
            )

            if requested_metrics:
                matched = definitions[
                    definitions["_canonical_metric"]
                    .isin(requested_metrics)
                ].copy()

            else:
                matched = definitions.copy()

            records: list[dict[str, Any]] = []

            for _, row in matched.iterrows():
                records.append({
                    "metric_name": self._clean_value(
                        row["Metric_Name"]
                    ),
                    "canonical_metric_name":
                        self._clean_value(
                            row["_canonical_metric"]
                        ),
                    "definition": self._clean_value(
                        row["Definition"]
                    ),
                    "calculation_logic":
                        self._clean_value(
                            row["Calculation_Logic"]
                        ),
                    "primary_source_table":
                        self._clean_value(
                            row[
                                "Primary_Source_Table"
                            ]
                        ),
                    "definition_source":
                        (
                            "Headcount_Management_"
                            "Metric_Definitions.csv"
                        ),
                })

            # Registered metric fallback when the CSV does not
            # contain the requested metric.
            found_canonical_names = {
                record["canonical_metric_name"]
                for record in records
            }

            for metric_name in requested_metrics:
                if metric_name in found_canonical_names:
                    continue

                definition = METRICS.get(metric_name)

                if definition is None:
                    continue

                records.append({
                    "metric_name":
                        definition.display_name,
                    "canonical_metric_name":
                        definition.name,
                    "definition":
                        definition.description,
                    "calculation_logic":
                        definition.formula
                        or definition.operation,
                    "primary_source_table":
                        ", ".join(
                            definition.source_tables
                        )
                        or None,
                    "definition_source":
                        "metric_registry.py",
                })

            if not records:
                raise HeadcountGovernanceNotFoundError(
                    "No matching Headcount metric definition "
                    "was found."
                )

            return HeadcountToolResult(
                status=HeadcountResultStatus.SUCCESS,
                question=plan.question,
                analysis_type=plan.analysis_type,
                message=(
                    "Headcount metric definition retrieval "
                    "completed successfully."
                ),
                resolved_scope={
                    "definition_count": len(records),
                },
                records=records,
                evidence_sources=[
                    "Headcount_Management_"
                    "Metric_Definitions.csv",
                ],
                data_as_of_date=self._organization_as_of_date(),
                calculation_notes=[
                    (
                        "Definitions and calculation logic are "
                        "retrieved from the metric-definition file."
                    ),
                    (
                        "The internal metric registry is used only "
                        "when a registered metric is absent from "
                        "the definition file."
                    ),
                ],
            )

        except HeadcountGovernanceNotFoundError as error:
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
                    "Metric definition retrieval could not "
                    "be completed."
                ),
                limitations=[str(error)],
                data_as_of_date=self._organization_as_of_date(),
            )

    # ========================================================
    # HEADCOUNT RULES
    # ========================================================

    def _execute_rules(
        self,
        plan: HeadcountQueryPlan,
    ) -> HeadcountToolResult:
        try:
            rules = self.repository.get_table(
                "rules"
            ).copy()

            rules["Effective_Start_Date"] = pd.to_datetime(
                rules["Effective_Start_Date"],
                errors="coerce",
            )

            rules["Effective_End_Date"] = pd.to_datetime(
                rules["Effective_End_Date"],
                errors="coerce",
            )

            as_of_date = self._organization_as_of_date()

            if as_of_date is not None:
                as_of_timestamp = pd.Timestamp(
                    as_of_date
                )

                rules = rules[
                    (
                        rules["Effective_Start_Date"]
                        .isna()
                        |
                        (
                            rules["Effective_Start_Date"]
                            <= as_of_timestamp
                        )
                    )
                    &
                    (
                        rules["Effective_End_Date"]
                        .isna()
                        |
                        (
                            rules["Effective_End_Date"]
                            >= as_of_timestamp
                        )
                    )
                ].copy()

            resolved_scope: dict[str, Any] = {
                "organization": "All",
                "rule_status": "Active",
            }

            if plan.scope.department is not None:
                department_id, department_name = (
                    self._resolve_department(
                        plan.scope.department
                    )
                )

                rules = rules[
                    (
                        rules["Rule_Scope"]
                        .astype("string")
                        .str.casefold()
                        .eq("all departments")
                    )
                    |
                    (
                        rules["Department_ID"]
                        .astype("string")
                        .str.casefold()
                        .eq(
                            department_id.casefold()
                        )
                    )
                ].copy()

                resolved_scope["department"] = (
                    department_name
                )

            question = plan.question.casefold()

            if "critical" in question:
                rules = rules[
                    rules["Severity"]
                    .astype("string")
                    .str.casefold()
                    .eq("critical")
                ]

                resolved_scope["severity"] = "Critical"

            elif "warning" in question:
                rules = rules[
                    rules["Severity"]
                    .astype("string")
                    .str.casefold()
                    .eq("warning")
                ]

                resolved_scope["severity"] = "Warning"

            elif "information" in question:
                rules = rules[
                    rules["Severity"]
                    .astype("string")
                    .str.casefold()
                    .eq("information")
                ]

                resolved_scope["severity"] = "Information"

            specific_rule_matches = (
                self._specific_rule_matches(
                    rules,
                    plan.question,
                )
            )

            if not specific_rule_matches.empty:
                rules = specific_rule_matches

            if rules.empty:
                raise HeadcountGovernanceNotFoundError(
                    "No active Headcount rules were found for "
                    "the requested scope."
                )

            records = []

            for _, row in rules.sort_values(
                "Rule_ID"
            ).iterrows():
                records.append({
                    "rule_id": self._clean_value(
                        row["Rule_ID"]
                    ),
                    "rule_name": self._clean_value(
                        row["Rule_Name"]
                    ),
                    "rule_scope": self._clean_value(
                        row["Rule_Scope"]
                    ),
                    "department_id": self._clean_value(
                        row["Department_ID"]
                    ),
                    "metric_name": self._clean_value(
                        row["Metric_Name"]
                    ),
                    "comparison_operator":
                        self._clean_value(
                            row[
                                "Comparison_Operator"
                            ]
                        ),
                    "threshold_value":
                        self._clean_value(
                            row["Threshold_Value"]
                        ),
                    "severity": self._clean_value(
                        row["Severity"]
                    ),
                    "rule_description":
                        self._clean_value(
                            row["Rule_Description"]
                        ),
                    "effective_start_date":
                        self._clean_value(
                            row[
                                "Effective_Start_Date"
                            ]
                        ),
                    "effective_end_date":
                        self._clean_value(
                            row[
                                "Effective_End_Date"
                            ]
                        ),
                })

            if "all" not in question:
                records = records[:plan.limit]

            definition = METRICS[
                "active_rule_count"
            ]

            metric_result = HeadcountMetricResult(
                metric_name="active_rule_count",
                display_name=definition.display_name,
                value=int(len(rules)),
                unit=definition.unit,
            )

            return HeadcountToolResult(
                status=HeadcountResultStatus.SUCCESS,
                question=plan.question,
                analysis_type=plan.analysis_type,
                message=(
                    "Headcount Management rule retrieval "
                    "completed successfully."
                ),
                resolved_scope=resolved_scope,
                metrics=[metric_result],
                records=records,
                evidence_sources=[
                    "Headcount_Management_Rules.csv",
                    "Department_Master.csv",
                ],
                data_as_of_date=as_of_date,
                calculation_notes=[
                    (
                        "Active rules are selected using their "
                        "effective start and end dates."
                    ),
                    (
                        "Department queries include both global "
                        "rules and rules specific to the department."
                    ),
                ],
            )

        except HeadcountGovernanceNotFoundError as error:
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
                    "Headcount Management rule retrieval could "
                    "not be completed."
                ),
                limitations=[str(error)],
                data_as_of_date=self._organization_as_of_date(),
            )

    def _resolve_department(
        self,
        requested_value: str,
    ) -> tuple[str, str]:
        departments = self.repository.get_table(
            "departments"
        )

        normalized = requested_value.strip().casefold()

        id_values = (
            departments["Department_ID"]
            .astype("string")
            .str.strip()
            .str.casefold()
        )

        name_values = (
            departments["Department_Name"]
            .astype("string")
            .str.strip()
            .str.casefold()
        )

        matches = departments[
            id_values.eq(normalized)
            | name_values.eq(normalized)
        ]

        if matches.empty:
            matches = departments[
                name_values.str.contains(
                    re.escape(normalized),
                    regex=True,
                    na=False,
                )
            ]

        if len(matches) != 1:
            raise HeadcountGovernanceNotFoundError(
                f"The requested department "
                f"{requested_value!r} was not found uniquely."
            )

        row = matches.iloc[0]

        return (
            str(row["Department_ID"]),
            str(row["Department_Name"]),
        )

    @staticmethod
    def _specific_rule_matches(
        rules: pd.DataFrame,
        question: str,
    ) -> pd.DataFrame:
        normalized_question = (
            normalize_registry_term(question)
        )

        generic_terms = {
            "rule",
            "rules",
            "headcount",
            "workforce",
            "staffing",
            "policy",
            "policies",
            "threshold",
            "thresholds",
            "alert",
            "watch",
            "limit",
            "requirement",
            "requirements",
            "escalation",
            "coverage",
            "capacity",
            "ratio",
            "show",
            "what",
            "which",
            "apply",
            "applies",
        }

        matching_indexes: list[Any] = []

        for index, row in rules.iterrows():
            normalized_rule_name = (
                normalize_registry_term(
                    str(row["Rule_Name"])
                )
            )

            if normalized_rule_name in normalized_question:
                matching_indexes.append(index)
                continue

            significant_tokens = [
                token
                for token in normalized_rule_name.split("_")
                if token not in generic_terms
            ]

            if (
                len(significant_tokens) >= 2
                and all(
                    token in normalized_question
                    for token in significant_tokens
                )
            ):
                matching_indexes.append(index)

        if not matching_indexes:
            return rules.iloc[0:0].copy()

        return rules.loc[
            matching_indexes
        ].copy()

    # ========================================================
    # COMMON HELPERS
    # ========================================================

    @staticmethod
    def _filter_name(
        dataframe: pd.DataFrame,
        *,
        column: str,
        id_column: str | None,
        requested_value: str,
        label: str,
    ) -> pd.DataFrame:
        normalized = requested_value.strip().casefold()

        values = (
            dataframe[column]
            .astype("string")
            .str.strip()
            .str.casefold()
        )

        exact_mask = values.eq(normalized)

        if id_column is not None:
            ids = (
                dataframe[id_column]
                .astype("string")
                .str.strip()
                .str.casefold()
            )

            exact_mask = (
                exact_mask
                | ids.eq(normalized)
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

        unique_values = partial[
            column
        ].dropna().unique()

        if len(unique_values) == 1:
            return partial.copy()

        raise HeadcountGovernanceNotFoundError(
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
    def _exception_as_of_date(
        dataframe: pd.DataFrame,
    ) -> date | None:
        value = dataframe[
            "detected_date"
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