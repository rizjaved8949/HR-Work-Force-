from __future__ import annotations

import re
from datetime import date
from typing import Any, Protocol

import pandas as pd

from .data_repository import DecisionCaseDataRepository
from .rule_catalog import DecisionTriggerRuleCatalog
from .schemas import DecisionCaseDraft
from .successor_readiness import DeterministicSuccessorReadiness


class InvokableTool(Protocol):
    def invoke(self, input: dict[str, Any]) -> dict[str, Any]: ...


ATTRITION_REASON_LABELS = {
    "Tenure_Months": "employee tenure",
    "Monthly_Salary_PKR": "current salary level",
    "Salary_vs_Market_pct": "salary competitiveness against the market",
    "Last_Increment_pct": "recent salary increment",
    "Months_Since_Last_Promotion": "time since the last promotion",
    "KPI_Achievement_pct": "KPI achievement pattern",
    "Performance_Trend_6M": "recent performance trend",
    "Overtime_Hours_Last_30D": "recent overtime workload",
    "Engagement_Score": "employee engagement",
    "Job_Satisfaction_Score": "job satisfaction",
    "Work_Life_Balance_Score": "work-life balance",
    "Manager_Relationship_Score": "relationship with the manager",
    "Career_Growth_Score": "career-growth opportunities",
    "Pay_Concern_Raised_Last_6M": "a recently raised pay concern",
}


class DecisionTriggerEngine:
    """Detect high-value HR cases from current data, never from hardcoded case rows.

    Five rule definitions are enabled/disabled in HR_Decision_Trigger_Rules.csv.
    Every evaluation reads fresh source data, runs deterministic criteria, and
    returns only the cases that currently match. Existing HR source data is
    read-only; this module never changes employee/workforce records.
    """

    def __init__(
        self,
        *,
        data_repository: DecisionCaseDataRepository,
        attrition_prediction_tool: InvokableTool,
        successor_readiness: DeterministicSuccessorReadiness | Any | None = None,
        rule_catalog: DecisionTriggerRuleCatalog | None = None,
    ) -> None:
        self.data = data_repository
        self.attrition_prediction_tool = attrition_prediction_tool
        self.successor_readiness = successor_readiness or DeterministicSuccessorReadiness(
            data_repository
        )
        self.rules = rule_catalog or DecisionTriggerRuleCatalog(
            data_repository.data_dir / "HR_Decision_Trigger_Rules.csv"
        )

    @staticmethod
    def _date(value: Any) -> date | None:
        if value is None or pd.isna(value):
            return None
        parsed = pd.to_datetime(value, errors="coerce")
        if pd.isna(parsed):
            return None
        return parsed.date()

    @staticmethod
    def _safe_number(value: Any) -> int | float | None:
        number = pd.to_numeric(value, errors="coerce")
        if pd.isna(number):
            return None
        number = float(number)
        return int(number) if number.is_integer() else round(number, 2)

    @staticmethod
    def _text_equals(series: pd.Series, value: str) -> pd.Series:
        return series.astype("string").fillna("").str.strip().str.casefold().eq(value.casefold())

    def detect(self) -> list[DecisionCaseDraft]:
        # Rebuild deterministic successor evidence from the newest data once per
        # evaluation. Test doubles may not implement refresh(), so keep this
        # optional and side-effect free for unit tests.
        refresh = getattr(self.successor_readiness, "refresh", None)
        if callable(refresh):
            refresh()

        drafts: list[DecisionCaseDraft] = []

        if self.rules.enabled("DTE-001"):
            drafts.extend(self._detect_retention_and_continuity())
        if self.rules.enabled("DTE-002"):
            drafts.extend(self._detect_critical_role_performance_decline())
        if self.rules.enabled("DTE-003"):
            drafts.extend(self._detect_unbudgeted_filled_positions())
        if self.rules.enabled("DTE-004"):
            drafts.extend(self._detect_critical_vacancy_escalation())
        if self.rules.enabled("DTE-005"):
            drafts.extend(self._detect_long_open_critical_vacancy_backlog())

        return self._merge_same_employee_cases(drafts)

    # ------------------------------------------------------------------
    # DTE-001: strong performer + critical role + attrition Yes + no
    # Ready Now successor. This is intentionally narrow to avoid alert spam.
    # ------------------------------------------------------------------
    def _detect_retention_and_continuity(self) -> list[DecisionCaseDraft]:
        rule = self.rules.get("DTE-001")
        profiles = self.data.read("profiles")
        performance = self.data.read("performance_summary")
        positions = self.data.read("positions")
        attrition = self.data.read("attrition")

        profile_cols = [
            "Employee_ID", "Employee_Name", "Department", "Department_ID",
            "Position_ID", "Position_Title", "Employee_Status", "Data_As_Of_Date",
        ]
        perf_cols = [
            "Employee_ID", "Latest_Performance_Score", "Latest_Performance_Band",
            "Performance_Trend", "Three_Month_Change_Points", "Data_As_Of_Date",
        ]
        position_cols = ["Position_ID", "Position_Criticality"]

        merged = (
            profiles[profile_cols]
            .merge(
                performance[perf_cols],
                on="Employee_ID",
                how="left",
                suffixes=("_profile", "_performance"),
            )
            .merge(positions[position_cols], on="Position_ID", how="left")
        )

        candidates = merged[
            self._text_equals(merged["Employee_Status"], "Active")
            & self._text_equals(merged["Position_Criticality"], "Critical")
            & merged["Latest_Performance_Band"].astype("string").isin(
                ["Strong", "Exceptional"]
            )
        ].copy()

        attrition_by_employee = {
            str(row["Employee_ID"]).strip(): row
            for row in attrition.to_dict("records")
            if str(row.get("Employee_ID", "")).strip()
        }

        drafts: list[DecisionCaseDraft] = []
        for _, row in candidates.iterrows():
            employee_id = str(row["Employee_ID"]).strip()
            attrition_record = attrition_by_employee.get(employee_id)
            if not attrition_record:
                continue

            prediction = self.attrition_prediction_tool.invoke({
                "employee_record": {
                    "status": "found",
                    "records": {"attrition_features": attrition_record},
                }
            })
            if str(prediction.get("attrition", "")).strip().casefold() != "yes":
                continue

            successor = self.successor_readiness.evaluate(employee_id)
            if successor.get("status") != "success":
                # Missing successor evidence must not be interpreted as proof of
                # a succession gap. That would create a false positive.
                continue
            if successor.get("has_ready_now"):
                continue

            raw_reasons = list(prediction.get("top_reasons") or [])
            reason_labels = [
                ATTRITION_REASON_LABELS.get(name, name) for name in raw_reasons
            ]
            data_as_of = self._date(row.get("Data_As_Of_Date_profile")) or self._date(
                row.get("Data_As_Of_Date_performance")
            )

            drafts.append(DecisionCaseDraft(
                case_key=f"EMPLOYEE:{employee_id}",
                rule_id=rule.rule_id,
                case_type=rule.rule_name,
                subject_type="Employee",
                subject_id=employee_id,
                employee_id=employee_id,
                position_id=str(row["Position_ID"]),
                department_id=str(row["Department_ID"]),
                department=str(row["Department"]),
                priority=rule.priority,
                display_rank=rule.display_rank,
                title=f"Critical retention and succession gap - {row['Employee_Name']}",
                reason=(
                    "A Strong/Exceptional performer in a Critical position has an existing "
                    "CatBoost attrition prediction of Yes and no Ready Now successor in the "
                    "deterministic successor ranking."
                ),
                evidence={
                    "employee_id": employee_id,
                    "employee_name": str(row["Employee_Name"]),
                    "department": str(row["Department"]),
                    "position_id": str(row["Position_ID"]),
                    "position_title": str(row["Position_Title"]),
                    "position_criticality": "Critical",
                    "performance_score": self._safe_number(
                        row.get("Latest_Performance_Score")
                    ),
                    "performance_band": str(row.get("Latest_Performance_Band")),
                    "performance_trend": str(row.get("Performance_Trend")),
                    "attrition_prediction": "Yes",
                    "attrition_contributing_factors": reason_labels,
                    "ready_now_successor": False,
                    "successor_candidate_count": successor.get("candidate_count"),
                    "top_successor": successor.get("top_candidate"),
                },
                suggested_action=rule.suggested_action,
                data_as_of=data_as_of,
            ))

        # Within this equally Critical rule, surface the highest-performing key
        # role first. This uses actual performance data, not an invented score.
        return sorted(
            drafts,
            key=lambda item: (
                -float(item.evidence.get("performance_score") or 0),
                item.employee_id or "",
            ),
        )

    # ------------------------------------------------------------------
    # DTE-002: declining performance in a Critical position.
    # ------------------------------------------------------------------
    def _detect_critical_role_performance_decline(self) -> list[DecisionCaseDraft]:
        rule = self.rules.get("DTE-002")
        profiles = self.data.read("profiles")
        performance = self.data.read("performance_summary")
        positions = self.data.read("positions")

        merged = (
            performance.merge(
                profiles[["Employee_ID", "Employee_Status"]],
                on="Employee_ID",
                how="left",
            )
            .merge(
                positions[["Position_ID", "Position_Criticality"]],
                on="Position_ID",
                how="left",
            )
        )

        candidates = merged[
            self._text_equals(merged["Employee_Status"], "Active")
            & self._text_equals(merged["Position_Criticality"], "Critical")
            & self._text_equals(merged["Performance_Trend"], "Declining")
        ].copy()

        drafts: list[DecisionCaseDraft] = []
        for _, row in candidates.iterrows():
            employee_id = str(row["Employee_ID"]).strip()
            drafts.append(DecisionCaseDraft(
                case_key=f"EMPLOYEE:{employee_id}",
                rule_id=rule.rule_id,
                case_type=rule.rule_name,
                subject_type="Employee",
                subject_id=employee_id,
                employee_id=employee_id,
                position_id=str(row["Position_ID"]),
                department_id=str(row["Department_ID"]),
                department=str(row["Department"]),
                priority=rule.priority,
                display_rank=rule.display_rank,
                title=f"Critical-role performance trend declining - {row['Employee_Name']}",
                reason=(
                    "An active employee holding a Critical position has Performance_Trend = "
                    "Declining in the existing performance summary."
                ),
                evidence={
                    "employee_id": employee_id,
                    "employee_name": str(row["Employee_Name"]),
                    "department": str(row["Department"]),
                    "position_id": str(row["Position_ID"]),
                    "position_title": str(row["Position_Title"]),
                    "position_criticality": "Critical",
                    "latest_performance_score": self._safe_number(
                        row.get("Latest_Performance_Score")
                    ),
                    "latest_performance_band": str(row.get("Latest_Performance_Band")),
                    "performance_trend": "Declining",
                    "three_month_change_points": self._safe_number(
                        row.get("Three_Month_Change_Points")
                    ),
                    "development_kpi_1": row.get("Development_KPI_1"),
                    "development_kpi_1_score": self._safe_number(
                        row.get("Development_KPI_1_Score")
                    ),
                },
                suggested_action=rule.suggested_action,
                data_as_of=self._date(row.get("Data_As_Of_Date")),
            ))

        # More negative three-month change appears first inside the same rule.
        return sorted(
            drafts,
            key=lambda item: (
                float(item.evidence.get("three_month_change_points") or 0),
                item.employee_id or "",
            ),
        )

    # ------------------------------------------------------------------
    # DTE-003: consume an already-deterministic Critical headcount exception
    # and aggregate all affected positions into one dashboard case.
    # ------------------------------------------------------------------
    def _detect_unbudgeted_filled_positions(self) -> list[DecisionCaseDraft]:
        rule = self.rules.get("DTE-003")
        exceptions = self.data.read("headcount_exceptions")
        positions = self.data.read("positions")

        matches = exceptions[
            self._text_equals(exceptions["Exception_Status"], "Open")
            & self._text_equals(
                exceptions["Exception_Type"], "Filled Position Without Approved Budget"
            )
            & self._text_equals(exceptions["Severity"], "Critical")
        ].copy()
        if matches.empty:
            return []

        position_ids: list[str] = []
        for text in matches["Exception_Description"].fillna("").astype(str):
            position_ids.extend(
                re.findall(r"\bPOS-[A-Z0-9-]+\b", text, flags=re.IGNORECASE)
            )
        position_ids = sorted(set(position_ids))

        detail_columns = [
            "Position_ID", "Position_Title", "Department", "Current_Employee_ID",
            "Current_Employee_Name", "Budgeted_Position", "Approved_Position",
        ]
        details = positions[
            positions["Position_ID"].astype(str).isin(position_ids)
        ][detail_columns].copy()

        evidence_positions = [
            {
                "position_id": str(row["Position_ID"]),
                "position_title": str(row["Position_Title"]),
                "department": str(row["Department"]),
                "employee_id": None
                if pd.isna(row["Current_Employee_ID"])
                else str(row["Current_Employee_ID"]),
                "employee_name": None
                if pd.isna(row["Current_Employee_Name"])
                else str(row["Current_Employee_Name"]),
                "budgeted_position": str(row["Budgeted_Position"]),
                "approved_position": str(row["Approved_Position"]),
            }
            for _, row in details.iterrows()
        ]

        departments = sorted(set(matches["Department_Name"].dropna().astype(str)))
        detected_dates = pd.to_datetime(matches["Detected_Date"], errors="coerce").dropna()
        data_as_of = detected_dates.max().date() if not detected_dates.empty else None

        return [DecisionCaseDraft(
            case_key="ORGANIZATION:UNBUDGETED_FILLED_POSITIONS",
            rule_id=rule.rule_id,
            case_type=rule.rule_name,
            subject_type="Organization",
            subject_id="ORGANIZATION",
            priority=rule.priority,
            display_rank=rule.display_rank,
            title="Filled positions without approved budget",
            reason=(
                f"{len(matches)} open Critical headcount exception(s) show filled positions "
                "that are not included in the approved position budget. They are grouped "
                "into one case so the dashboard is not flooded."
            ),
            evidence={
                "exception_count": int(len(matches)),
                "departments": departments,
                "positions": evidence_positions,
                "source_exception_type": "Filled Position Without Approved Budget",
                "source_severity": "Critical",
            },
            suggested_action=rule.suggested_action,
            data_as_of=data_as_of,
        )]

    # ------------------------------------------------------------------
    # DTE-004: source threshold comes from existing Headcount RULE-004.
    # No age threshold is invented in this module.
    # ------------------------------------------------------------------
    def _detect_critical_vacancy_escalation(self) -> list[DecisionCaseDraft]:
        rule = self.rules.get("DTE-004")
        if not rule.source_rule_id:
            raise ValueError(
                "DTE-004 must reference the existing Headcount rule that supplies its threshold."
            )

        source_rules = self.data.read("headcount_rules")
        vacancies = self.data.read("vacancy_history")

        source_match = source_rules[
            self._text_equals(source_rules["Rule_ID"], rule.source_rule_id)
        ]
        if source_match.empty:
            raise ValueError(
                f"Source Headcount rule {rule.source_rule_id} for DTE-004 was not found."
            )

        threshold = pd.to_numeric(
            source_match.iloc[0]["Threshold_Value"], errors="coerce"
        )
        if pd.isna(threshold):
            raise ValueError(
                f"Source Headcount rule {rule.source_rule_id} has a non-numeric vacancy threshold."
            )
        threshold = float(threshold)

        age = pd.to_numeric(vacancies["Vacancy_Age_in_Days"], errors="coerce")
        status = vacancies["Vacancy_Status"].astype("string").fillna("").str.strip().str.casefold()
        matches = vacancies[
            status.isin({"currently open", "open"})
            & self._text_equals(vacancies["Position_Criticality"], "Critical")
            & age.gt(threshold)
        ].copy()
        if matches.empty:
            return []

        matches["_age"] = pd.to_numeric(matches["Vacancy_Age_in_Days"], errors="coerce")
        matches = matches.sort_values(
            ["_age", "Position_ID"], ascending=[False, True]
        )
        top_positions = [
            {
                "position_id": str(row["Position_ID"]),
                "position_title": str(row["Position_Title"]),
                "department_id": str(row["Department_ID"]),
                "department": str(row["Department_Name"]),
                "vacancy_age_days": self._safe_number(row.get("Vacancy_Age_in_Days")),
                "recruitment_stage": str(row.get("Recruitment_Stage")),
                "target_fill_date": None
                if pd.isna(row.get("Target_Fill_Date"))
                else str(row.get("Target_Fill_Date")),
            }
            for _, row in matches.head(5).iterrows()
        ]

        data_dates = pd.to_datetime(matches["Data_As_Of_Date"], errors="coerce").dropna()
        data_as_of = data_dates.max().date() if not data_dates.empty else None

        return [DecisionCaseDraft(
            case_key="ORGANIZATION:CRITICAL_VACANCY_ESCALATION",
            rule_id=rule.rule_id,
            case_type=rule.rule_name,
            subject_type="Organization",
            subject_id="ORGANIZATION",
            priority=rule.priority,
            display_rank=rule.display_rank,
            title="Critical positions open beyond the allowed vacancy age",
            reason=(
                f"{len(matches)} currently open Critical position(s) exceed the existing "
                f"{rule.source_rule_id} threshold of {int(threshold) if threshold.is_integer() else threshold} days."
            ),
            evidence={
                "critical_vacancy_count": int(len(matches)),
                "vacancy_age_threshold_days": self._safe_number(threshold),
                "source_headcount_rule_id": rule.source_rule_id,
                "source_headcount_rule_name": str(source_match.iloc[0]["Rule_Name"]),
                "top_positions": top_positions,
            },
            suggested_action=rule.suggested_action,
            data_as_of=data_as_of,
        )]

    # ------------------------------------------------------------------
    # DTE-005: existing headcount register has Critical-severity long-open
    # exceptions. Aggregate the enterprise backlog into one case.
    # ------------------------------------------------------------------
    def _detect_long_open_critical_vacancy_backlog(self) -> list[DecisionCaseDraft]:
        rule = self.rules.get("DTE-005")
        exceptions = self.data.read("headcount_exceptions")

        matches = exceptions[
            self._text_equals(exceptions["Exception_Status"], "Open")
            & self._text_equals(exceptions["Exception_Type"], "Long-Open Vacancies")
            & self._text_equals(exceptions["Severity"], "Critical")
        ].copy()
        if matches.empty:
            return []

        matches["_count"] = pd.to_numeric(
            matches["Current_Value"], errors="coerce"
        ).fillna(0)
        matches = matches.sort_values(
            ["_count", "Department_Name"], ascending=[False, True]
        )
        total_positions = int(matches["_count"].sum())
        top_departments = [
            {
                "department_id": str(row["Department_ID"]),
                "department": str(row["Department_Name"]),
                "long_open_vacancies": int(row["_count"]),
            }
            for _, row in matches.head(5).iterrows()
        ]
        detected_dates = pd.to_datetime(matches["Detected_Date"], errors="coerce").dropna()
        data_as_of = detected_dates.max().date() if not detected_dates.empty else None

        return [DecisionCaseDraft(
            case_key="ORGANIZATION:LONG_OPEN_CRITICAL_VACANCY_BACKLOG",
            rule_id=rule.rule_id,
            case_type=rule.rule_name,
            subject_type="Organization",
            subject_id="ORGANIZATION",
            priority=rule.priority,
            display_rank=rule.display_rank,
            title="Critical-severity long-open vacancy backlog",
            reason=(
                f"Existing headcount governance data contains {len(matches)} open "
                f"Critical-severity long-open vacancy exception(s), representing "
                f"{total_positions} positions in total. They are grouped into one case."
            ),
            evidence={
                "affected_department_count": int(len(matches)),
                "long_open_vacancy_count": total_positions,
                "top_affected_departments": top_departments,
                "metric_name": str(matches.iloc[0]["Metric_Name"]),
                "source_exception_type": "Long-Open Vacancies",
                "source_severity": "Critical",
            },
            suggested_action=rule.suggested_action,
            data_as_of=data_as_of,
        )]

    @staticmethod
    def _merge_same_employee_cases(drafts: list[DecisionCaseDraft]) -> list[DecisionCaseDraft]:
        """Avoid two dashboard cards for the same employee when rules overlap."""

        by_key: dict[str, DecisionCaseDraft] = {}
        priority_weight = {"Critical": 4, "High": 3, "Medium": 2, "Low": 1}

        for draft in drafts:
            existing = by_key.get(draft.case_key)
            if existing is None:
                by_key[draft.case_key] = draft
                continue

            if (
                priority_weight[draft.priority] > priority_weight[existing.priority]
                or (
                    priority_weight[draft.priority] == priority_weight[existing.priority]
                    and draft.display_rank < existing.display_rank
                )
            ):
                primary, secondary = draft, existing
            else:
                primary, secondary = existing, draft

            evidence = dict(primary.evidence)
            additional = list(evidence.get("additional_triggers") or [])
            additional.append({
                "rule_id": secondary.rule_id,
                "case_type": secondary.case_type,
                "priority": secondary.priority,
                "reason": secondary.reason,
                "evidence": secondary.evidence,
            })
            evidence["additional_triggers"] = additional
            by_key[draft.case_key] = primary.model_copy(update={"evidence": evidence})

        return sorted(
            by_key.values(),
            key=lambda item: (
                {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}[item.priority],
                item.display_rank,
                item.case_key,
            ),
        )
