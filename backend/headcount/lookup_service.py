"""Employee and position lookup service for Headcount Management.

This module handles detailed employee and position questions.

It is isolated from:
- Attrition prediction;
- replacement recommendations;
- current Headcount aggregation;
- FastAPI endpoints.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

import pandas as pd

from headcount.repository import HeadcountRepository
from headcount.schemas import (
    HeadcountAnalysisType,
    HeadcountQueryPlan,
    HeadcountResultStatus,
    HeadcountToolResult,
)


class HeadcountLookupError(RuntimeError):
    """Base error for Headcount lookup operations."""


class HeadcountLookupNotFoundError(
    HeadcountLookupError
):
    """Raised when an employee or position is not found."""


class HeadcountLookupAmbiguousError(
    HeadcountLookupError
):
    """Raised when a name or title matches multiple records."""


class HeadcountLookupInputError(
    HeadcountLookupError
):
    """Raised when no lookup entity was provided."""


class HeadcountLookupService:
    """Perform deterministic employee and position lookups."""

    def __init__(
        self,
        repository: HeadcountRepository,
    ) -> None:
        self.repository = repository

    def execute(
        self,
        plan: HeadcountQueryPlan,
    ) -> HeadcountToolResult:
        """Execute an employee or position lookup."""

        try:
            if (
                plan.analysis_type
                == HeadcountAnalysisType.EMPLOYEE_LOOKUP
            ):
                return self._lookup_employee(plan)

            if (
                plan.analysis_type
                == HeadcountAnalysisType.POSITION_LOOKUP
            ):
                return self._lookup_position(plan)

            return HeadcountToolResult(
                status=HeadcountResultStatus.UNSUPPORTED,
                question=plan.question,
                analysis_type=plan.analysis_type,
                message=(
                    "The requested analysis is not an employee "
                    "or position lookup."
                ),
                data_as_of_date=self._data_as_of_date(),
            )

        except HeadcountLookupInputError as error:
            return HeadcountToolResult(
                status=HeadcountResultStatus.INVALID_REQUEST,
                question=plan.question,
                analysis_type=plan.analysis_type,
                message=str(error),
                data_as_of_date=self._data_as_of_date(),
            )

        except HeadcountLookupNotFoundError as error:
            return HeadcountToolResult(
                status=HeadcountResultStatus.NOT_FOUND,
                question=plan.question,
                analysis_type=plan.analysis_type,
                message=str(error),
                data_as_of_date=self._data_as_of_date(),
            )

        except HeadcountLookupAmbiguousError as error:
            return HeadcountToolResult(
                status=HeadcountResultStatus.INVALID_REQUEST,
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
                    "The Headcount lookup could not be completed."
                ),
                limitations=[str(error)],
                data_as_of_date=self._data_as_of_date(),
            )

    # ========================================================
    # EMPLOYEE LOOKUP
    # ========================================================

    def _lookup_employee(
        self,
        plan: HeadcountQueryPlan,
    ) -> HeadcountToolResult:
        employees = self.repository.get_table(
            "employees"
        )

        employee = self._resolve_single_record(
            dataframe=employees,
            id_column="Employee_ID",
            name_column="Employee_Name",
            requested_id=plan.scope.employee_id,
            requested_name=plan.scope.employee_name,
            question=plan.question,
            entity_label="employee",
        )

        employee_id = str(
            employee["Employee_ID"]
        )

        manager_name: str | None = None
        manager_position_title: str | None = None

        manager_id = self._clean_value(
            employee.get("Manager_Employee_ID")
        )

        if manager_id is not None:
            manager_matches = employees[
                employees["Employee_ID"]
                .astype("string")
                .str.casefold()
                .eq(str(manager_id).casefold())
            ]

            if not manager_matches.empty:
                manager = manager_matches.iloc[0]

                manager_name = self._clean_value(
                    manager.get("Employee_Name")
                )

                manager_position_title = self._clean_value(
                    manager.get("Position_Title")
                )

        positions = self.repository.get_table(
            "positions"
        )

        position_matches = positions[
            positions["Position_ID"]
            .astype("string")
            .str.casefold()
            .eq(
                str(
                    employee["Position_ID"]
                ).casefold()
            )
        ]

        position_status: str | None = None
        position_criticality: str | None = None
        approved_position: str | None = None
        budgeted_position: str | None = None

        if not position_matches.empty:
            position = position_matches.iloc[0]

            position_status = self._clean_value(
                position.get("Position_Status")
            )

            position_criticality = self._clean_value(
                position.get("Position_Criticality")
            )

            approved_position = self._clean_value(
                position.get("Approved_Position")
            )

            budgeted_position = self._clean_value(
                position.get("Budgeted_Position")
            )

        organizational_unit_name = (
            self._lookup_reference_name(
                table_name="organizational_units",
                id_column="Organizational_Unit_ID",
                name_column="Organizational_Unit_Name",
                requested_id=employee.get(
                    "Organizational_Unit_ID"
                ),
            )
        )

        work_location = self._lookup_reference_record(
            table_name="work_locations",
            id_column="Work_Location_ID",
            requested_id=employee.get(
                "Work_Location_ID"
            ),
        )

        cost_center_name = self._lookup_reference_name(
            table_name="cost_centers",
            id_column="Cost_Center_ID",
            name_column="Cost_Center_Name",
            requested_id=employee.get(
                "Cost_Center_ID"
            ),
        )

        record: dict[str, Any] = {
            "employee_id": employee_id,
            "employee_name": self._clean_value(
                employee.get("Employee_Name")
            ),
            "employee_status": self._clean_value(
                employee.get("Employee_Status")
            ),
            "department_id": self._clean_value(
                employee.get("Department_ID")
            ),
            "department": self._clean_value(
                employee.get("Department")
            ),
            "business_unit": self._clean_value(
                employee.get("Business_Unit")
            ),
            "organizational_unit_id": self._clean_value(
                employee.get("Organizational_Unit_ID")
            ),
            "organizational_unit_name": (
                organizational_unit_name
            ),
            "position_id": self._clean_value(
                employee.get("Position_ID")
            ),
            "position_title": self._clean_value(
                employee.get("Position_Title")
            ),
            "designation": self._clean_value(
                employee.get("Designation")
            ),
            "job_level": self._clean_value(
                employee.get("Job_Level")
            ),
            "career_level": self._clean_value(
                employee.get("Career_Level")
            ),
            "employment_type": self._clean_value(
                employee.get("Employment_Type")
            ),
            "employee_category": self._clean_value(
                employee.get("Employee_Category")
            ),
            "work_mode": self._clean_value(
                employee.get("Work_Mode")
            ),
            "shift_type": self._clean_value(
                employee.get("Shift_Type")
            ),
            "work_location_id": self._clean_value(
                employee.get("Work_Location_ID")
            ),
            "work_location_name": self._clean_value(
                work_location.get(
                    "Work_Location_Name"
                )
                if work_location is not None
                else None
            ),
            "city": self._clean_value(
                work_location.get("City")
                if work_location is not None
                else None
            ),
            "cost_center_id": self._clean_value(
                employee.get("Cost_Center_ID")
            ),
            "cost_center_name": cost_center_name,
            "manager_employee_id": manager_id,
            "manager_name": manager_name,
            "manager_position_title": (
                manager_position_title
            ),
            "hire_date": self._clean_value(
                employee.get("Hire_Date")
            ),
            "tenure_months": self._clean_value(
                employee.get("Tenure_Months")
            ),
            "years_in_company": self._clean_value(
                employee.get("Years_in_Company")
            ),
            "current_assignment_start_date": (
                self._clean_value(
                    employee.get(
                        "Current_Assignment_Start_Date"
                    )
                )
            ),
            "included_in_approved_headcount": (
                self._clean_value(
                    employee.get(
                        "Included_in_Approved_Headcount"
                    )
                )
            ),
            "headcount_inclusion_category": (
                self._clean_value(
                    employee.get(
                        "Headcount_Inclusion_Category"
                    )
                )
            ),
            "position_status": position_status,
            "approved_position": approved_position,
            "budgeted_position": budgeted_position,
            "position_criticality": (
                position_criticality
            ),
            "vacancy_planning_status": (
                self._clean_value(
                    employee.get(
                        "Vacancy_Planning_Status"
                    )
                )
            ),
        }

        return HeadcountToolResult(
            status=HeadcountResultStatus.SUCCESS,
            question=plan.question,
            analysis_type=plan.analysis_type,
            message=(
                "Employee Headcount details were found."
            ),
            resolved_scope={
                "employee_id": employee_id,
                "employee_name": record[
                    "employee_name"
                ],
            },
            records=[record],
            evidence_sources=[
                "Employee_Profile.csv",
                "Position_Master.csv",
                "Organizational_Unit_Master.csv",
                "Work_Location_Master.csv",
                "Cost_Center_Master.csv",
            ],
            data_as_of_date=self._data_as_of_date(),
            calculation_notes=[
                (
                    "The employee record represents the current "
                    "profile and assignment as of the reporting date."
                )
            ],
        )

    # ========================================================
    # POSITION LOOKUP
    # ========================================================

    def _lookup_position(
        self,
        plan: HeadcountQueryPlan,
    ) -> HeadcountToolResult:
        positions = self.repository.get_table(
            "positions"
        )

        position = self._resolve_single_record(
            dataframe=positions,
            id_column="Position_ID",
            name_column="Position_Title",
            requested_id=plan.scope.position_id,
            requested_name=plan.scope.position_title,
            question=plan.question,
            entity_label="position",
        )

        position_id = str(
            position["Position_ID"]
        )

        organizational_unit_name = (
            self._lookup_reference_name(
                table_name="organizational_units",
                id_column="Organizational_Unit_ID",
                name_column="Organizational_Unit_Name",
                requested_id=position.get(
                    "Organizational_Unit_ID"
                ),
            )
        )

        work_location = self._lookup_reference_record(
            table_name="work_locations",
            id_column="Work_Location_ID",
            requested_id=position.get(
                "Work_Location_ID"
            ),
        )

        cost_center_name = self._lookup_reference_name(
            table_name="cost_centers",
            id_column="Cost_Center_ID",
            name_column="Cost_Center_Name",
            requested_id=position.get(
                "Cost_Center_ID"
            ),
        )

        vacancy_age_in_days: int | None = None

        vacancy_start_date = self._clean_value(
            position.get("Vacancy_Start_Date")
        )

        position_status = self._clean_value(
            position.get("Position_Status")
        )

        if (
            position_status in {"Vacant", "Frozen"}
            and vacancy_start_date is not None
        ):
            start_date = pd.Timestamp(
                vacancy_start_date
            ).date()

            as_of_date = self._data_as_of_date()

            if as_of_date is not None:
                vacancy_age_in_days = (
                    as_of_date - start_date
                ).days

        record: dict[str, Any] = {
            "position_id": position_id,
            "position_title": self._clean_value(
                position.get("Position_Title")
            ),
            "designation": self._clean_value(
                position.get("Designation")
            ),
            "department_id": self._clean_value(
                position.get("Department_ID")
            ),
            "department": self._clean_value(
                position.get("Department")
            ),
            "business_unit": self._clean_value(
                position.get("Business_Unit")
            ),
            "organizational_unit_id": self._clean_value(
                position.get("Organizational_Unit_ID")
            ),
            "organizational_unit_name": (
                organizational_unit_name
            ),
            "work_location_id": self._clean_value(
                position.get("Work_Location_ID")
            ),
            "work_location_name": self._clean_value(
                work_location.get(
                    "Work_Location_Name"
                )
                if work_location is not None
                else None
            ),
            "city": self._clean_value(
                work_location.get("City")
                if work_location is not None
                else None
            ),
            "cost_center_id": self._clean_value(
                position.get("Cost_Center_ID")
            ),
            "cost_center_name": cost_center_name,
            "job_level": self._clean_value(
                position.get("Job_Level")
            ),
            "employment_type": self._clean_value(
                position.get("Employment_Type")
            ),
            "work_mode_requirement": self._clean_value(
                position.get("Work_Mode_Requirement")
            ),
            "shift_requirement": self._clean_value(
                position.get("Shift_Requirement")
            ),
            "position_status": position_status,
            "approved_position": self._clean_value(
                position.get("Approved_Position")
            ),
            "budgeted_position": self._clean_value(
                position.get("Budgeted_Position")
            ),
            "full_time_equivalent_capacity": (
                self._clean_value(
                    position.get(
                        "Full_Time_Equivalent_Capacity"
                    )
                )
            ),
            "current_employee_id": self._clean_value(
                position.get("Current_Employee_ID")
            ),
            "current_employee_name": self._clean_value(
                position.get("Current_Employee_Name")
            ),
            "position_criticality": self._clean_value(
                position.get("Position_Criticality")
            ),
            "vacancy_planning_status": self._clean_value(
                position.get("Vacancy_Planning_Status")
            ),
            "vacancy_start_date": vacancy_start_date,
            "vacancy_age_in_days": vacancy_age_in_days,
            "position_freeze_status": self._clean_value(
                position.get("Position_Freeze_Status")
            ),
            "reporting_position_id": self._clean_value(
                position.get("Reporting_Position_ID")
            ),
            "reporting_title": self._clean_value(
                position.get("Reporting_Title")
            ),
            "annual_salary_budget": self._clean_value(
                position.get("Annual_Salary_Budget")
            ),
            "annual_benefits_budget": self._clean_value(
                position.get("Annual_Benefits_Budget")
            ),
            "headcount_inclusion_category": (
                self._clean_value(
                    position.get(
                        "Headcount_Inclusion_Category"
                    )
                )
            ),
        }

        return HeadcountToolResult(
            status=HeadcountResultStatus.SUCCESS,
            question=plan.question,
            analysis_type=plan.analysis_type,
            message=(
                "Position Headcount details were found."
            ),
            resolved_scope={
                "position_id": position_id,
                "position_title": record[
                    "position_title"
                ],
            },
            records=[record],
            evidence_sources=[
                "Position_Master.csv",
                "Organizational_Unit_Master.csv",
                "Work_Location_Master.csv",
                "Cost_Center_Master.csv",
            ],
            data_as_of_date=self._data_as_of_date(),
            calculation_notes=[
                (
                    "Vacancy age is calculated from the vacancy "
                    "start date to the reporting date."
                )
            ],
        )

    # ========================================================
    # RECORD RESOLUTION
    # ========================================================

    def _resolve_single_record(
        self,
        *,
        dataframe: pd.DataFrame,
        id_column: str,
        name_column: str,
        requested_id: str | None,
        requested_name: str | None,
        question: str,
        entity_label: str,
    ) -> pd.Series:
        """Resolve one employee or position safely."""

        if requested_id is not None:
            matches = dataframe[
                dataframe[id_column]
                .astype("string")
                .str.casefold()
                .eq(requested_id.strip().casefold())
            ]

            if matches.empty:
                raise HeadcountLookupNotFoundError(
                    f"The requested {entity_label} ID "
                    f"{requested_id!r} was not found."
                )

            return matches.iloc[0]

        if requested_name is not None:
            return self._resolve_by_name(
                dataframe=dataframe,
                name_column=name_column,
                requested_name=requested_name,
                entity_label=entity_label,
            )

        detected_id = self._find_known_value_in_question(
            question=question,
            values=dataframe[id_column],
        )

        if detected_id is not None:
            matches = dataframe[
                dataframe[id_column]
                .astype("string")
                .str.casefold()
                .eq(detected_id.casefold())
            ]

            if not matches.empty:
                return matches.iloc[0]

        detected_name = (
            self._find_known_value_in_question(
                question=question,
                values=dataframe[name_column],
            )
        )

        if detected_name is not None:
            return self._resolve_by_name(
                dataframe=dataframe,
                name_column=name_column,
                requested_name=detected_name,
                entity_label=entity_label,
            )

        raise HeadcountLookupInputError(
            f"Please provide a valid {entity_label} ID "
            f"or {entity_label} name."
        )

    def _resolve_by_name(
        self,
        *,
        dataframe: pd.DataFrame,
        name_column: str,
        requested_name: str,
        entity_label: str,
    ) -> pd.Series:
        """Resolve one exact or uniquely partial name."""

        normalized_name = (
            requested_name.strip().casefold()
        )

        names = (
            dataframe[name_column]
            .astype("string")
            .str.strip()
            .str.casefold()
        )

        exact_matches = dataframe[
            names.eq(normalized_name)
        ]

        if len(exact_matches) == 1:
            return exact_matches.iloc[0]

        if len(exact_matches) > 1:
            raise HeadcountLookupAmbiguousError(
                f"Multiple {entity_label} records match "
                f"{requested_name!r}. Please provide the ID."
            )

        partial_matches = dataframe[
            names.str.contains(
                re.escape(normalized_name),
                regex=True,
                na=False,
            )
        ]

        if len(partial_matches) == 1:
            return partial_matches.iloc[0]

        if partial_matches.empty:
            raise HeadcountLookupNotFoundError(
                f"The requested {entity_label} "
                f"{requested_name!r} was not found."
            )

        raise HeadcountLookupAmbiguousError(
            f"Multiple {entity_label} records partially match "
            f"{requested_name!r}. Please provide the ID."
        )

    @staticmethod
    def _find_known_value_in_question(
        *,
        question: str,
        values: pd.Series,
    ) -> str | None:
        """Find a complete known value inside the question."""

        normalized_question = question.casefold()

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
            pattern = (
                rf"(?<!\w)"
                rf"{re.escape(known_value.casefold())}"
                rf"(?!\w)"
            )

            if re.search(
                pattern,
                normalized_question,
            ):
                return known_value

        return None

    # ========================================================
    # MASTER TABLE LOOKUPS
    # ========================================================

    def _lookup_reference_name(
        self,
        *,
        table_name: str,
        id_column: str,
        name_column: str,
        requested_id: Any,
    ) -> str | None:
        record = self._lookup_reference_record(
            table_name=table_name,
            id_column=id_column,
            requested_id=requested_id,
        )

        if record is None:
            return None

        return self._clean_value(
            record.get(name_column)
        )

    def _lookup_reference_record(
        self,
        *,
        table_name: str,
        id_column: str,
        requested_id: Any,
    ) -> pd.Series | None:
        clean_id = self._clean_value(
            requested_id
        )

        if clean_id is None:
            return None

        dataframe = self.repository.get_table(
            table_name
        )

        matches = dataframe[
            dataframe[id_column]
            .astype("string")
            .str.casefold()
            .eq(str(clean_id).casefold())
        ]

        if matches.empty:
            return None

        return matches.iloc[0]

    # ========================================================
    # VALUE HELPERS
    # ========================================================

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

    def _data_as_of_date(self) -> date | None:
        value = self.repository.get_data_as_of_date()

        if value is None:
            return None

        try:
            return date.fromisoformat(value)
        except ValueError:
            return None