"""Read-only lookup helpers for the dedicated Scenario Simulator UI.

This module exposes search/context/options views only. It does not perform any
simulation arithmetic and never mutates existing HR datasets.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from .config import JOB_LEVEL_ORDER
from .errors import SimulationDataError
from .repository import SimulationRepository
from .schemas import ScenarioType


def _native(value: Any) -> Any:
    """Convert pandas/numpy scalar values into JSON-safe Python values."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    return value


def _compact_position(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "position_id": _native(row.get("Position_ID")),
        "position_title": _native(row.get("Position_Title")),
        "designation": _native(row.get("Designation")),
        "department_id": _native(row.get("Department_ID")),
        "department": _native(row.get("Department")),
        "job_level": _native(row.get("Job_Level")),
        "position_status": _native(row.get("Position_Status")),
        "position_criticality": _native(row.get("Position_Criticality")),
        "available": str(row.get("Position_Status", "")).strip().lower() == "vacant",
    }


class SimulationLookupService:
    """Frontend-facing read-only lookup service for Scenario Simulator forms."""

    def __init__(self, repository: SimulationRepository):
        self.repository = repository

    def list_scenarios(self) -> list[dict[str, Any]]:
        catalog = self.repository.get("scenario_catalog").copy()
        records = []
        for _, row in catalog.iterrows():
            raw = row.to_dict()
            records.append({
                "code": _native(raw.get("Scenario_Code")),
                "name": _native(raw.get("Scenario_Name")),
                "level": _native(raw.get("Scenario_Level")),
                "description": _native(raw.get("Description")),
                "required_inputs": _native(raw.get("Required_Inputs")),
            })
        return records

    def search_employees(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        query = (query or "").strip()
        if not query:
            return []

        profile = self.repository.get("employee_profile").copy()
        normalized = query.casefold()

        searchable_columns = [
            "Employee_ID",
            "Employee_Name",
            "Department",
            "Position_Title",
            "Designation",
        ]
        mask = pd.Series(False, index=profile.index)
        for column in searchable_columns:
            mask = mask | profile[column].fillna("").astype(str).str.casefold().str.contains(
                normalized,
                regex=False,
            )

        result = profile.loc[mask].head(max(1, min(limit, 50)))
        return [
            {
                "employee_id": _native(row.get("Employee_ID")),
                "employee_name": _native(row.get("Employee_Name")),
                "department_id": _native(row.get("Department_ID")),
                "department": _native(row.get("Department")),
                "position_id": _native(row.get("Position_ID")),
                "position_title": _native(row.get("Position_Title")),
                "designation": _native(row.get("Designation")),
                "job_level": _native(row.get("Job_Level")),
                "employee_status": _native(row.get("Employee_Status")),
            }
            for row in result.to_dict(orient="records")
        ]

    def list_departments(self, query: str = "", limit: int = 50) -> list[dict[str, Any]]:
        frame = self.repository.get("headcount_summary").copy()
        query = (query or "").strip().casefold()
        if query:
            mask = (
                frame["Department_ID"].fillna("").astype(str).str.casefold().str.contains(query, regex=False)
                | frame["Department_Name"].fillna("").astype(str).str.casefold().str.contains(query, regex=False)
            )
            frame = frame.loc[mask]

        frame = frame.head(max(1, min(limit, 100)))
        return [
            {
                "department_id": _native(row.get("Department_ID")),
                "department_name": _native(row.get("Department_Name")),
                "business_unit": _native(row.get("Business_Unit")),
                "actual_headcount": _native(row.get("Actual_Employee_Count")),
                "vacancies": _native(row.get("Vacant_Approved_Position_Count")),
                "budget_utilization_pct": _native(row.get("Budget_Utilization_Percentage")),
            }
            for row in frame.to_dict(orient="records")
        ]

    def employee_context(self, employee_id: str) -> dict[str, Any]:
        ctx = self.repository.employee_context(employee_id)
        employee = ctx["employee"] or {}
        performance = ctx.get("performance") or {}
        experience = ctx.get("experience") or {}
        attendance = ctx.get("attendance") or {}
        features = ctx.get("simulation_features") or {}
        position = ctx.get("position") or {}

        manager = None
        manager_id = employee.get("Manager_Employee_ID")
        if manager_id:
            try:
                manager = self.repository.resolve_employee(str(manager_id))
            except Exception:
                manager = None

        salary = None
        if "attrition_features" in self.repository._frames:
            row = self.repository._one("attrition_features", "Employee_ID", employee_id)
            if row:
                salary = _native(row.get("Monthly_Salary_PKR"))

        return {
            "employee": {
                "employee_id": _native(employee.get("Employee_ID")),
                "employee_name": _native(employee.get("Employee_Name")),
                "department_id": _native(employee.get("Department_ID")),
                "department": _native(employee.get("Department")),
                "position_id": _native(employee.get("Position_ID")),
                "position_title": _native(employee.get("Position_Title")),
                "designation": _native(employee.get("Designation")),
                "job_level": _native(employee.get("Job_Level")),
                "employment_type": _native(employee.get("Employment_Type")),
                "work_mode": _native(employee.get("Work_Mode")),
                "hire_date": _native(employee.get("Hire_Date")),
                "tenure_months": _native(employee.get("Tenure_Months")),
                "years_in_company": _native(employee.get("Years_in_Company")),
                "manager_employee_id": _native(manager_id),
                "manager_name": _native(manager.get("Employee_Name")) if manager else None,
                "monthly_salary_pkr": salary,
            },
            "performance": {
                "latest_score": _native(performance.get("Latest_Performance_Score")),
                "latest_band": _native(performance.get("Latest_Performance_Band")),
                "average_12m_score": _native(performance.get("Average_12M_Performance_Score")),
                "trend": _native(performance.get("Performance_Trend")),
            },
            "experience": {
                "total_experience_years": _native(experience.get("Total_Experience_Years")),
                "relevant_experience_years": _native(experience.get("Relevant_Experience_Years")),
                "years_in_current_role": _native(experience.get("Years_in_Current_Role")),
            },
            "attendance": {
                "attendance_score": _native(attendance.get("Attendance_Score")),
                "overtime_hours_last_30d": _native(attendance.get("Overtime_Hours_Last_30D")),
            },
            "simulation_features": {
                "promotion_readiness_pct": _native(features.get("Promotion_Base_Readiness_Score_pct")),
                "transfer_readiness_pct": _native(features.get("Transfer_Base_Readiness_Score_pct")),
                "reskilling_readiness_pct": _native(features.get("Reskilling_Base_Readiness_Score_pct")),
                "reskilling_need_pct": _native(features.get("Reskilling_Need_Score_pct")),
                "current_role_skill_coverage_pct": _native(features.get("Current_Role_Skill_Coverage_pct")),
                "mandatory_skill_coverage_pct": _native(features.get("Current_Role_Mandatory_Skill_Coverage_pct")),
                "mandatory_skill_gap_count": _native(features.get("Current_Role_Mandatory_Gap_Count")),
            },
            "position": {
                "position_status": _native(position.get("Position_Status")),
                "position_criticality": _native(position.get("Position_Criticality")),
            },
        }

    def scenario_options(
        self,
        scenario_type: ScenarioType,
        employee_id: str | None = None,
        department_id: str | None = None,
        target_department_id: str | None = None,
        query: str = "",
        limit: int = 100,
    ) -> dict[str, Any]:
        if scenario_type == ScenarioType.EMPLOYEE_PROMOTION:
            if not employee_id:
                raise SimulationDataError("employee_id is required to load promotion options.")
            employee = self.repository.resolve_employee(employee_id)
            current_level = str(employee.get("Job_Level", ""))
            current_rank = JOB_LEVEL_ORDER.get(current_level, -1)
            frame = self.repository.positions_for_department(str(employee["Department_ID"]))
            frame = frame[
                frame["Job_Level"].astype(str).map(lambda value: JOB_LEVEL_ORDER.get(value, -1)) > current_rank
            ]
            positions = [_compact_position(row) for row in frame.to_dict(orient="records")]
            positions.sort(key=lambda item: (not item["available"], JOB_LEVEL_ORDER.get(str(item["job_level"]), 999), str(item["position_title"])))
            return {"target_positions": positions[:limit]}

        if scenario_type == ScenarioType.EMPLOYEE_TRANSFER:
            current_department_id = None
            if employee_id:
                current_department_id = str(self.repository.resolve_employee(employee_id).get("Department_ID"))
            departments = self.list_departments(query=query, limit=limit)
            if current_department_id:
                departments = [d for d in departments if str(d["department_id"]) != current_department_id]

            positions: list[dict[str, Any]] = []
            if target_department_id:
                frame = self.repository.positions_for_department(target_department_id)
                positions = [_compact_position(row) for row in frame.to_dict(orient="records")]
                positions.sort(key=lambda item: (not item["available"], str(item["position_title"])))
            return {
                "target_departments": departments,
                "target_positions": positions[:limit],
            }

        if scenario_type == ScenarioType.SKILL_RESKILLING:
            frame = self.repository.get("learning_business").copy()
            normalized = (query or "").strip().casefold()
            if normalized:
                mask = (
                    frame["Course_ID"].fillna("").astype(str).str.casefold().str.contains(normalized, regex=False)
                    | frame["Course_Name"].fillna("").astype(str).str.casefold().str.contains(normalized, regex=False)
                    | frame["Skill_Name"].fillna("").astype(str).str.casefold().str.contains(normalized, regex=False)
                )
                frame = frame.loc[mask]
            frame = frame.head(max(1, min(limit, 100)))
            courses = []
            for row in frame.to_dict(orient="records"):
                courses.append({
                    "course_id": _native(row.get("Course_ID")),
                    "course_name": _native(row.get("Course_Name")),
                    "skill_id": _native(row.get("Skill_ID")),
                    "skill_name": _native(row.get("Skill_Name")),
                    "course_level": _native(row.get("Course_Level")),
                    "estimated_training_cost_pkr": _native(row.get("Estimated_Training_Cost_PKR")),
                    "expected_time_to_competency_days": _native(row.get("Expected_Time_to_Competency_Days")),
                })
            return {"courses": courses}

        if scenario_type in {
            ScenarioType.HEADCOUNT_REDUCTION,
            ScenarioType.WORKFORCE_EXPANSION,
            ScenarioType.BUDGET_CHANGE,
            ScenarioType.BUSINESS_DEMAND_CHANGE,
        }:
            return {"departments": self.list_departments(query=query, limit=limit)}

        raise SimulationDataError(f"Unsupported scenario type: {scenario_type.value}")
