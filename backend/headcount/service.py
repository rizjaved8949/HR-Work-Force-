"""Deterministic Headcount calculation service.

This first service version handles current Headcount, positions,
vacancies, staffing gaps, department breakdowns and rankings.

All numerical values are calculated from CSV data. The LLM will only
explain these results later.
"""
from __future__ import annotations
from headcount.budget_service import (
   BUDGET_METRICS,
    HeadcountBudgetService,
)
from headcount.governance_service import (
    GOVERNANCE_METRICS,
    HeadcountGovernanceService,
)
from headcount.schemas import (
    AnalyzeHeadcountInput,
    HeadcountAnalysisType,
    HeadcountMetricResult,
    HeadcountQueryPlan,
    HeadcountResultStatus,
    HeadcountToolResult,
    SortDirection,
)
from headcount.history_service import (
    HISTORY_METRICS,
  HeadcountHistoryService,
)
from headcount.daily_service import (
    DAILY_ACTIVITY_METRICS,
    DAILY_ONLY_METRICS,
    HeadcountDailyService,
)
from headcount.lookup_service import (
    HeadcountLookupService,
)
from headcount.vacancy_service import (
    VACANCY_DETAIL_ONLY_METRICS,
    HeadcountVacancyService,
)

import re
from datetime import date
from typing import Any, Final

import pandas as pd
from headcount.workforce_service import (
    WORKFORCE_COMPOSITION_ONLY_METRICS,
    HeadcountWorkforceService,
    should_use_workforce_service,
)
from headcount.combined_service import (
    HeadcountCombinedService,
)
from headcount.metric_registry import METRICS
from headcount.query_planner import (
    COMPARISON_TERMS,
    DEFINITION_TERMS,
    GENERAL_HEADCOUNT_TERMS,
    RANKING_TERMS,
    RULE_TERMS,
    TREND_TERMS,
    _extract_identifiers,
    _infer_dimensions,
    _infer_metrics,
    create_headcount_query_plan,
)
from headcount.repository import HeadcountRepository



class HeadcountCalculationError(RuntimeError):
    """Raised when a Headcount calculation cannot be completed."""


class HeadcountScopeNotFoundError(
    HeadcountCalculationError
):
    """Raised when a department or business unit is not found."""


CURRENT_HEADCOUNT_METRICS: Final[set[str]] = {
    "actual_employee_count",
    "actual_full_time_equivalent",
    "approved_position_count",
    "budgeted_position_count",
    "filled_position_count",
    "vacant_position_count",
    "frozen_position_count",
    "vacant_approved_position_count",
    "funded_vacant_position_count",
    "unfunded_vacant_position_count",
    "headcount_variance",
    "net_approved_headcount_gap",
    "net_budgeted_headcount_gap",
    "vacancy_rate_percentage",
    "headcount_utilization_percentage",
    "overstaffed_employee_count",
}


SUMMABLE_METRICS: Final[tuple[str, ...]] = (
    "actual_employee_count",
    "actual_full_time_equivalent",
    "approved_position_count",
    "budgeted_position_count",
    "filled_position_count",
    "vacant_position_count",
    "frozen_position_count",
    "vacant_approved_position_count",
    "funded_vacant_position_count",
    "unfunded_vacant_position_count",
    "overstaffed_employee_count",
)


INTEGER_METRICS: Final[set[str]] = {
    "actual_employee_count",
    "approved_position_count",
    "budgeted_position_count",
    "filled_position_count",
    "vacant_position_count",
    "frozen_position_count",
    "vacant_approved_position_count",
    "funded_vacant_position_count",
    "unfunded_vacant_position_count",
    "headcount_variance",
    "net_approved_headcount_gap",
    "net_budgeted_headcount_gap",
    "overstaffed_employee_count",
}


class HeadcountService:
    """Execute validated Headcount query plans against CSV data."""

    def __init__(
        self,
        repository: HeadcountRepository,
    ) -> None:
        self.repository = repository

        self.lookup_service = HeadcountLookupService(
            repository
        )
        self.budget_service = HeadcountBudgetService(
            repository
        )
        self.history_service = HeadcountHistoryService(
            repository
        )
        self.daily_service = HeadcountDailyService(
            repository
        )
        self.governance_service = (
            HeadcountGovernanceService(
                repository
            )
        )
        self.workforce_service = (
            HeadcountWorkforceService(
                repository
            )
        )
        self.vacancy_service = HeadcountVacancyService(
            repository
        )
        self.combined_service = (
            HeadcountCombinedService(
                current_executor=self.execute,
                budget_service=self.budget_service,
                daily_service=self.daily_service,
                governance_service=(
                    self.governance_service
                ),
                history_service=self.history_service,
                vacancy_service=self.vacancy_service,
                workforce_service=(
                    self.workforce_service
                ),
            )
        )

    @staticmethod
    def _resolve_service_domains(
        plan: HeadcountQueryPlan,
    ) -> set[str]:
        """Identify which isolated services a plan requires.

        Metric categories are not the same as service boundaries.
        For example, Headcount, position, and basic vacancy metrics
        are all handled by the current Headcount service.
        """

        domains: set[str] = set()

        historical_context = (
            plan.analysis_type
            in {
                HeadcountAnalysisType.TREND,
                HeadcountAnalysisType.MOVEMENT,
            }
            or plan.date_range is not None
        )

        for metric in plan.metrics:
            if metric == "expected_employee_exits":
                domains.add("attrition")

            elif metric in DAILY_ONLY_METRICS:
                domains.add("daily")

            elif metric in GOVERNANCE_METRICS:
                domains.add("governance")

            elif metric in VACANCY_DETAIL_ONLY_METRICS:
                domains.add("vacancy")

            elif (
                metric
                in WORKFORCE_COMPOSITION_ONLY_METRICS
            ):
                domains.add("workforce")

            elif (
                historical_context
                and metric in HISTORY_METRICS
            ):
                domains.add("history")

            elif metric in BUDGET_METRICS:
                domains.add("budget")

            elif metric in CURRENT_HEADCOUNT_METRICS:
                domains.add("current")

        if (
            plan.analysis_type
            == HeadcountAnalysisType.EXCEPTION
        ):
            domains.add("governance")

        elif (
            plan.analysis_type
            == HeadcountAnalysisType.DEFINITION
        ):
            domains.add("governance")

        elif (
            plan.analysis_type
            == HeadcountAnalysisType.RULE
        ):
            domains.add("governance")

        elif (
            plan.analysis_type
            == HeadcountAnalysisType.AVAILABILITY
        ):
            domains.add("daily")

        elif plan.analysis_type in {
            HeadcountAnalysisType.TREND,
            HeadcountAnalysisType.MOVEMENT,
        }:
            domains.add("history")

        elif (
            plan.analysis_type
            == HeadcountAnalysisType.BUDGET
        ):
            domains.add("budget")

        elif (
            plan.analysis_type
            == HeadcountAnalysisType.VACANCY
        ):
            domains.add("vacancy")

        return domains

    @staticmethod
    def _question_has_headcount_signal(
        request: AnalyzeHeadcountInput,
    ) -> bool:
        """Return True when the request refers to something recognizable.

        The planner falls back to an organization-wide OVERVIEW whenever it
        recognizes nothing, so an unrelated question or a typo came back as
        a confident, fully-populated answer to a question nobody asked.
        """

        # Anything the caller stated explicitly is a signal on its own.
        if (
            request.metrics
            or request.group_by
            or request.filters
            or request.analysis_type is not None
            or request.date_range is not None
        ):
            return True

        question = request.question.lower()

        # Any recognized metric, dimension, or keyword counts.
        if _infer_metrics(request.question):
            return True

        if _infer_dimensions(request.question):
            return True

        # Any resolved scope field at all -- an employee, a position, a
        # department, a work location -- means the question names something
        # real. Read from the model rather than a hand-listed subset so a
        # new scope field cannot silently stop counting as a signal.
        scope = _extract_identifiers(
            request.question,
            request.scope,
        )

        if scope.model_dump(exclude_none=True):
            return True

        return any(
            term in question
            for term in (
                *RULE_TERMS,
                *RANKING_TERMS,
                *TREND_TERMS,
                *COMPARISON_TERMS,
                *DEFINITION_TERMS,
                *GENERAL_HEADCOUNT_TERMS,
            )
        )

    def analyze(
        self,
        request: AnalyzeHeadcountInput,
    ) -> HeadcountToolResult:
        """Create a query plan and execute it."""

        if not self._question_has_headcount_signal(request):
            return HeadcountToolResult(
                status=HeadcountResultStatus.UNSUPPORTED,
                question=request.question,
                analysis_type=HeadcountAnalysisType.OVERVIEW,
                message=(
                    "This question could not be matched to any "
                    "Headcount metric, dimension, or scope. Please "
                    "rephrase it in terms of headcount, positions, "
                    "vacancies, budget, or workforce movement."
                ),
                limitations=[
                    "No recognizable Headcount terms were found "
                    "in the question."
                ],
                data_as_of_date=self._data_as_of_date(),
            )

        plan = create_headcount_query_plan(request)
        return self.execute(plan)

    def execute(
        self,
        plan: HeadcountQueryPlan,
    ) -> HeadcountToolResult:
        """Execute one validated Headcount query plan."""

        # Employee and position detail lookups
        if plan.analysis_type in {
            HeadcountAnalysisType.EMPLOYEE_LOOKUP,
            HeadcountAnalysisType.POSITION_LOOKUP,
        }:
            return self.lookup_service.execute(plan)
        # ----------------------------------------------------
        # EXPLICIT SINGLE-SERVICE ROUTING
        # ----------------------------------------------------

        # Definitions, rules, and exceptions must use the
        # governance datasets before combined routing.
        if plan.analysis_type in {
            HeadcountAnalysisType.EXCEPTION,
            HeadcountAnalysisType.DEFINITION,
            HeadcountAnalysisType.RULE,
        }:
            return self.governance_service.execute(
                plan
            )

        # Explicit detailed vacancy requests must preserve
        # funding, criticality, and vacancy-age filters.
        if (
            plan.analysis_type
            == HeadcountAnalysisType.VACANCY
        ):
            return self.vacancy_service.execute(
                plan
            )

        # Daily time-series requests must keep chronological
        # ordering and must not be merged by CombinedService.
        if "activity_date" in plan.group_by:
            return self.daily_service.execute(
                plan
            )

        service_domains = (
            self._resolve_service_domains(plan)
        )

        # Use the combined orchestrator only when the request
        # genuinely needs more than one isolated service.
        #
        # Do not rely only on analysis_type == COMBINED because
        # the planner may classify core Headcount + position +
        # basic vacancy metrics as different categories even
        # though one current Headcount service handles them all.
        if len(service_domains) > 1:
            return self.combined_service.execute(
                plan
            )

        if any(
            metric in VACANCY_DETAIL_ONLY_METRICS
            for metric in plan.metrics
        ):
            return self.vacancy_service.execute(plan)

        if (
            plan.group_by
            and plan.group_by[0] in {
                "position",
                "recruitment_stage",
                "position_criticality",
                "vacancy_status",
            }
        ):
            return self.vacancy_service.execute(plan)

        if (
            plan.metrics
            and set(plan.metrics).issubset(
                GOVERNANCE_METRICS
            )
        ):
            return self.governance_service.execute(
                plan
            )
        if (
            plan.analysis_type
            == HeadcountAnalysisType.AVAILABILITY
        ):
            return self.daily_service.execute(plan)

        if (
            plan.metrics
            and any(
                metric in DAILY_ONLY_METRICS
                for metric in plan.metrics
            )
            and set(plan.metrics).issubset(
                DAILY_ACTIVITY_METRICS
            )
        ):
            return self.daily_service.execute(plan)
        if plan.analysis_type in {
            HeadcountAnalysisType.TREND,
            HeadcountAnalysisType.MOVEMENT,
        }:
            return self.history_service.execute(plan)

        if (
            plan.date_range is not None
            and plan.metrics
            and set(plan.metrics).issubset(
                HISTORY_METRICS
            )
        ):
            return self.history_service.execute(plan)
        # Budget questions can also be ranking, breakdown,
        # comparison or metric questions. Therefore, route by
        # metric category before checking the analysis type.
        if (
            plan.metrics
            and set(plan.metrics).issubset(
                BUDGET_METRICS
            )
        ):
            return self.budget_service.execute(plan)

        # This handles broad budget questions where the planner
        # identifies the budget intent but does not provide metrics.
        if (
            plan.analysis_type
            == HeadcountAnalysisType.BUDGET
        ):
            return self.budget_service.execute(plan)

        if should_use_workforce_service(plan):
            return self.workforce_service.execute(
                plan
            )

        unsupported_metrics = [
            metric
            for metric in plan.metrics
            if metric not in CURRENT_HEADCOUNT_METRICS
        ]

        if unsupported_metrics:
            return HeadcountToolResult(
                status=HeadcountResultStatus.UNSUPPORTED,
                question=plan.question,
                analysis_type=plan.analysis_type,
                message=(
                    "This service version does not yet support "
                    "all requested metrics."
                ),
                limitations=[
                    (
                        "Metrics not yet implemented in Step 6A: "
                        + ", ".join(unsupported_metrics)
                    )
                ],
                data_as_of_date=self._data_as_of_date(),
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
                    "This service version currently supports "
                    "department and business-unit grouping."
                ),
                limitations=[
                    (
                        "Unsupported grouping dimensions: "
                        + ", ".join(unsupported_grouping)
                    )
                ],
                data_as_of_date=self._data_as_of_date(),
            )

        if len(plan.group_by) > 1:
            return HeadcountToolResult(
                status=HeadcountResultStatus.UNSUPPORTED,
                question=plan.question,
                analysis_type=plan.analysis_type,
                message=(
                    "Step 6A supports one grouping dimension "
                    "at a time."
                ),
                limitations=[
                    (
                        "Multiple grouping dimensions will be "
                        "supported in a later service extension."
                    )
                ],
                data_as_of_date=self._data_as_of_date(),
            )

        try:
            department_frame = (
                self._build_department_headcount_frame()
            )

            scoped_frame, resolved_scope = (
                self._apply_scope(
                    department_frame,
                    plan,
                )
            )

            summary_frame = self._aggregate_frame(
                scoped_frame,
                group_by=None,
            )

            group_dimension = (
                plan.group_by[0]
                if plan.group_by
                else None
            )

            result_frame = self._aggregate_frame(
                scoped_frame,
                group_by=group_dimension,
            )

            result_frame = self._sort_and_limit(
                dataframe=result_frame,
                plan=plan,
            )

            metric_results = self._create_metric_results(
                summary_frame.iloc[0],
                plan.metrics,
            )

            records = (
                self._create_records(
                    dataframe=result_frame,
                    metrics=plan.metrics,
                    group_by=group_dimension,
                )
                if plan.include_details
                else []
            )

            calculation_notes = [
                (
                    "Actual employee count is calculated from "
                    "distinct current employee assignments."
                ),
                (
                    "Approved and budgeted counts are calculated "
                    "from Position_Master.csv."
                ),
                (
                    "Vacant approved positions are gross approved "
                    "positions with Vacant or Frozen status."
                ),
                (
                    "Net approved Headcount gap equals approved "
                    "positions minus actual employees."
                ),
            ]

            resolved_scope["group_by"] = (
                group_dimension or "organization"
            )

            return HeadcountToolResult(
                status=HeadcountResultStatus.SUCCESS,
                question=plan.question,
                analysis_type=plan.analysis_type,
                message=(
                    "Headcount calculation completed "
                    "successfully."
                ),
                resolved_scope=resolved_scope,
                metrics=metric_results,
                records=records,
                evidence_sources=[
                    "Employee_Assignment_History.csv",
                    "Position_Master.csv",
                    "Department_Master.csv",
                ],
                data_as_of_date=self._data_as_of_date(),
                calculation_notes=calculation_notes,
            )

        except HeadcountScopeNotFoundError as error:
            return HeadcountToolResult(
                status=HeadcountResultStatus.NOT_FOUND,
                question=plan.question,
                analysis_type=plan.analysis_type,
                message=str(error),
                data_as_of_date=self._data_as_of_date(),
            )

        except Exception as error:
            return HeadcountToolResult(
                status=HeadcountResultStatus.ERROR,
                question=plan.question,
                analysis_type=plan.analysis_type,
                message=(
                    "The Headcount calculation could not be "
                    "completed."
                ),
                limitations=[str(error)],
                data_as_of_date=self._data_as_of_date(),
            )

    # ========================================================
    # DATA PREPARATION
    # ========================================================

    def _build_department_headcount_frame(
        self,
    ) -> pd.DataFrame:
        """Build one reconciled current record per department."""

        departments = self.repository.get_table(
            "departments"
        )

        assignments = self.repository.get_table(
            "assignments"
        )

        positions = self.repository.get_table(
            "positions"
        )

        current_assignments = assignments[
            assignments["Assignment_Status"]
            .astype("string")
            .str.casefold()
            .eq("current")
        ].copy()

        current_assignments[
            "Assignment_Full_Time_Equivalent"
        ] = pd.to_numeric(
            current_assignments[
                "Assignment_Full_Time_Equivalent"
            ],
            errors="coerce",
        ).fillna(0.0)

        assignment_summary = (
            current_assignments
            .groupby(
                "Department_ID",
                dropna=False,
            )
            .agg(
                actual_employee_count=(
                    "Employee_ID",
                    "nunique",
                ),
                actual_full_time_equivalent=(
                    "Assignment_Full_Time_Equivalent",
                    "sum",
                ),
            )
            .reset_index()
        )

        positions = positions.copy()

        position_status = (
            positions["Position_Status"]
            .astype("string")
            .str.casefold()
        )

        approved_status = (
            positions["Approved_Position"]
            .astype("string")
            .str.casefold()
            .eq("yes")
        )

        budgeted_status = (
            positions["Budgeted_Position"]
            .astype("string")
            .str.casefold()
            .eq("yes")
        )

        open_status = position_status.isin(
            ["vacant", "frozen"]
        )

        positions["_approved"] = (
            approved_status.astype(int)
        )

        positions["_budgeted"] = (
            budgeted_status.astype(int)
        )

        positions["_filled"] = (
            position_status.eq("filled").astype(int)
        )

        positions["_vacant"] = (
            position_status.eq("vacant").astype(int)
        )

        positions["_frozen"] = (
            position_status.eq("frozen").astype(int)
        )

        positions["_vacant_approved"] = (
            open_status
            & approved_status
        ).astype(int)

        positions["_funded_vacant"] = (
            open_status
            & budgeted_status
        ).astype(int)

        positions["_unfunded_vacant"] = (
            open_status
            & approved_status
            & ~budgeted_status
        ).astype(int)

        position_summary = (
            positions
            .groupby(
                "Department_ID",
                dropna=False,
            )
            .agg(
                approved_position_count=(
                    "_approved",
                    "sum",
                ),
                budgeted_position_count=(
                    "_budgeted",
                    "sum",
                ),
                filled_position_count=(
                    "_filled",
                    "sum",
                ),
                vacant_position_count=(
                    "_vacant",
                    "sum",
                ),
                frozen_position_count=(
                    "_frozen",
                    "sum",
                ),
                vacant_approved_position_count=(
                    "_vacant_approved",
                    "sum",
                ),
                funded_vacant_position_count=(
                    "_funded_vacant",
                    "sum",
                ),
                unfunded_vacant_position_count=(
                    "_unfunded_vacant",
                    "sum",
                ),
            )
            .reset_index()
        )

        department_frame = departments[
            [
                "Department_ID",
                "Department_Name",
                "Business_Unit_Name",
            ]
        ].rename(
            columns={
                "Department_ID": "department_id",
                "Department_Name": "department",
                "Business_Unit_Name": "business_unit",
            }
        )

        department_frame = department_frame.merge(
            assignment_summary,
            left_on="department_id",
            right_on="Department_ID",
            how="left",
        ).drop(
            columns=["Department_ID"],
            errors="ignore",
        )

        department_frame = department_frame.merge(
            position_summary,
            left_on="department_id",
            right_on="Department_ID",
            how="left",
        ).drop(
            columns=["Department_ID"],
            errors="ignore",
        )

        for metric in SUMMABLE_METRICS:
            if metric not in department_frame.columns:
                department_frame[metric] = 0

            department_frame[metric] = pd.to_numeric(
                department_frame[metric],
                errors="coerce",
            ).fillna(0)

        department_frame[
            "overstaffed_employee_count"
        ] = (
            department_frame[
                "actual_employee_count"
            ]
            - department_frame[
                "approved_position_count"
            ]
        ).clip(lower=0)

        department_frame = self._add_derived_metrics(
            department_frame
        )

        return department_frame

    def _add_derived_metrics(
        self,
        dataframe: pd.DataFrame,
    ) -> pd.DataFrame:
        """Add deterministic derived metrics."""

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

        approved_denominator = (
            result["approved_position_count"]
            .replace(0, pd.NA)
        )

        result["vacancy_rate_percentage"] = (
            (
                result[
                    "vacant_approved_position_count"
                ]
                / approved_denominator
            )
            * 100
        ).round(2).fillna(0.0)

        result[
            "headcount_utilization_percentage"
        ] = (
            (
                result["actual_employee_count"]
                / approved_denominator
            )
            * 100
        ).round(2).fillna(0.0)

        return result

    # ========================================================
    # SCOPE RESOLUTION
    # ========================================================

    def _apply_scope(
        self,
        dataframe: pd.DataFrame,
        plan: HeadcountQueryPlan,
    ) -> tuple[pd.DataFrame, dict[str, Any]]:
        """Apply department or business-unit scope."""

        result = dataframe.copy()
        resolved_scope: dict[str, Any] = {
            "organization": "All",
        }

        requested_department = plan.scope.department

        if requested_department is None:
            requested_department = (
                self._find_name_in_question(
                    plan.question,
                    dataframe["department"],
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
                    plan.question,
                    dataframe["business_unit"],
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
            raise HeadcountScopeNotFoundError(
                "No Headcount data was found for the requested scope."
            )

        return result, resolved_scope

    def _filter_named_scope(
        self,
        *,
        dataframe: pd.DataFrame,
        requested_value: str,
        id_column: str | None,
        name_column: str,
        scope_label: str,
    ) -> pd.DataFrame:
        """Resolve an ID or name safely and case-insensitively."""

        normalized_value = str(
            requested_value
        ).strip().casefold()

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

        exact_matches = dataframe[exact_mask]

        if not exact_matches.empty:
            return exact_matches.copy()

        partial_mask = name_values.str.contains(
            re.escape(normalized_value),
            regex=True,
            na=False,
        )

        partial_matches = dataframe[partial_mask]

        unique_names = partial_matches[
            name_column
        ].dropna().unique()

        if len(unique_names) == 1:
            return partial_matches.copy()

        raise HeadcountScopeNotFoundError(
            f"The requested {scope_label} "
            f"{requested_value!r} was not found uniquely."
        )

    @staticmethod
    def _find_name_in_question(
        question: str,
        values: pd.Series,
    ) -> str | None:
        """Find a complete department or business-unit name.

        Word-boundary matching prevents short names such as "IT"
        from being incorrectly detected inside words such as
        "positions" or "unit".
        """

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

    def _aggregate_frame(
        self,
        dataframe: pd.DataFrame,
        group_by: str | None,
    ) -> pd.DataFrame:
        """Aggregate the department frame to the requested level."""

        if group_by == "department":
            return dataframe.copy()

        if group_by == "business_unit":
            result = (
                dataframe
                .groupby(
                    "business_unit",
                    dropna=False,
                )[list(SUMMABLE_METRICS)]
                .sum()
                .reset_index()
            )

            return self._add_derived_metrics(result)

        summary_values = {
            metric: dataframe[metric].sum()
            for metric in SUMMABLE_METRICS
        }

        result = pd.DataFrame(
            [summary_values]
        )

        result.insert(
            0,
            "organization",
            "All",
        )

        return self._add_derived_metrics(result)

    def _sort_and_limit(
        self,
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
            result = result.head(plan.limit)

        return result.reset_index(drop=True)

    # ========================================================
    # RESULT CREATION
    # ========================================================

    def _create_metric_results(
        self,
        summary_row: pd.Series,
        metrics: list[str],
    ) -> list[HeadcountMetricResult]:
        """Convert exact summary values into metric schemas."""

        results: list[HeadcountMetricResult] = []

        for metric_name in metrics:
            if metric_name not in summary_row.index:
                continue

            definition = METRICS[metric_name]

            raw_value = summary_row[metric_name]
            clean_value = self._clean_value(raw_value)

            numerator: int | float | None = None
            denominator: int | float | None = None

            if metric_name == "vacancy_rate_percentage":
                numerator = int(
                    summary_row[
                        "vacant_approved_position_count"
                    ]
                )

                denominator = int(
                    summary_row[
                        "approved_position_count"
                    ]
                )

            elif (
                metric_name
                == "headcount_utilization_percentage"
            ):
                numerator = int(
                    summary_row[
                        "actual_employee_count"
                    ]
                )

                denominator = int(
                    summary_row[
                        "approved_position_count"
                    ]
                )

            results.append(
                HeadcountMetricResult(
                    metric_name=metric_name,
                    display_name=definition.display_name,
                    value=clean_value,
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
        """Create JSON-safe grouped or detailed records."""

        identity_columns: list[str]

        if group_by == "department":
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

    @staticmethod
    def _clean_value(
        value: Any,
    ) -> Any:
        """Convert pandas and NumPy values into JSON-safe values."""

        if pd.isna(value):
            return None

        if hasattr(value, "item"):
            value = value.item()

        if isinstance(value, float):
            if value.is_integer():
                return int(value)

            return round(value, 2)

        return value

    def _data_as_of_date(self) -> date | None:
        """Return the repository reporting date as a date object."""

        value = self.repository.get_data_as_of_date()

        if value is None:
            return None

        try:
            return date.fromisoformat(value)
        except ValueError:
            return None