"""Read-only CSV repository for Headcount Management.

This module is completely separate from the existing Attrition and
successor pipelines. It only reads Headcount-related CSV files from
the shared Data directory.

Files are loaded lazily and cached after their first use.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Final

import pandas as pd


class HeadcountDataError(RuntimeError):
    """Raised when required Headcount data is unavailable or invalid."""


@dataclass(frozen=True)
class TableSpecification:
    """Configuration for one Headcount CSV table."""

    file_name: str
    required_columns: tuple[str, ...]
    date_columns: tuple[str, ...] = ()


TABLE_SPECIFICATIONS: Final[
    dict[str, TableSpecification]
] = {
    # ========================================================
    # ORGANIZATION AND HIERARCHY
    # ========================================================

    "organization": TableSpecification(
        file_name="Organization_Master.csv",
        required_columns=(
            "Organization_ID",
            "Organization_Name",
            "Currency",
            "Workforce_Data_As_Of_Date",
        ),
        date_columns=(
            "Workforce_Data_As_Of_Date",
        ),
    ),

    "business_units": TableSpecification(
        file_name="Business_Unit_Master.csv",
        required_columns=(
            "Business_Unit_ID",
            "Business_Unit_Name",
            "Organization_ID",
            "Active_Status",
        ),
        date_columns=(
            "Effective_Start_Date",
            "Effective_End_Date",
        ),
    ),

    "departments": TableSpecification(
        file_name="Department_Master.csv",
        required_columns=(
            "Department_ID",
            "Department_Name",
            "Business_Unit_ID",
            "Current_Employee_Count",
            "Approved_Position_Count",
            "Budgeted_Position_Count",
        ),
        date_columns=(
            "Effective_Start_Date",
            "Effective_End_Date",
        ),
    ),

    "organizational_units": TableSpecification(
        file_name="Organizational_Unit_Master.csv",
        required_columns=(
            "Organizational_Unit_ID",
            "Organizational_Unit_Name",
            "Organizational_Unit_Type",
            "Parent_Organizational_Unit_ID",
        ),
    ),

    "work_locations": TableSpecification(
        file_name="Work_Location_Master.csv",
        required_columns=(
            "Work_Location_ID",
            "Work_Location_Name",
            "Work_Location_Type",
            "City",
        ),
    ),

    "cost_centers": TableSpecification(
        file_name="Cost_Center_Master.csv",
        required_columns=(
            "Cost_Center_ID",
            "Cost_Center_Name",
            "Department_ID",
            "Currency",
        ),
        date_columns=(
            "Effective_Start_Date",
            "Effective_End_Date",
        ),
    ),

    # ========================================================
    # EMPLOYEES, POSITIONS AND ASSIGNMENTS
    # ========================================================

    "employees": TableSpecification(
        file_name="Employee_Profile.csv",
        required_columns=(
            "Employee_ID",
            "Employee_Name",
            "Department_ID",
            "Department",
            "Position_ID",
            "Job_Level",
            "Employee_Status",
            "Included_in_Approved_Headcount",
        ),
        date_columns=(
            "Hire_Date",
            "Current_Assignment_Start_Date",
            "Data_As_Of_Date",
        ),
    ),

    "positions": TableSpecification(
        file_name="Position_Master.csv",
        required_columns=(
            "Position_ID",
            "Position_Title",
            "Department_ID",
            "Department",
            "Position_Status",
            "Approved_Position",
            "Budgeted_Position",
            "Current_Employee_ID",
            "Position_Criticality",
        ),
        date_columns=(
            "Position_Approval_Date",
            "Position_Effective_Start_Date",
            "Position_Effective_End_Date",
            "Vacancy_Start_Date",
        ),
    ),

    "assignments": TableSpecification(
        file_name="Employee_Assignment_History.csv",
        required_columns=(
            "Assignment_ID",
            "Employee_ID",
            "Position_ID",
            "Department_ID",
            "Assignment_Status",
            "Assignment_Full_Time_Equivalent",
        ),
        date_columns=(
            "Assignment_Start_Date",
            "Assignment_End_Date",
            "Data_As_Of_Date",
        ),
    ),

    # ========================================================
    # CURRENT HEADCOUNT AND VACANCIES
    # ========================================================

    "current_summary": TableSpecification(
        file_name="Current_Headcount_Summary.csv",
        required_columns=(
            "Department_ID",
            "Department_Name",
            "Actual_Employee_Count",
            "Approved_Position_Count",
            "Budgeted_Position_Count",
            "Vacant_Approved_Position_Count",
            "Funded_Vacant_Position_Count",
            "Vacancy_Rate_Percentage",
        ),
        date_columns=(
            "Data_As_Of_Date",
        ),
    ),

    "vacancy_history": TableSpecification(
        file_name="Position_Vacancy_History.csv",
        required_columns=(
            "Vacancy_Record_ID",
            "Position_ID",
            "Department_ID",
            "Vacancy_Status",
            "Vacancy_Age_in_Days",
            "Budgeted_Position",
            "Position_Criticality",
            "Recruitment_Stage",
        ),
        date_columns=(
            "Vacancy_Start_Date",
            "Vacancy_End_Date",
            "Target_Fill_Date",
            "Data_As_Of_Date",
        ),
    ),

    # ========================================================
    # HISTORICAL HEADCOUNT AND MOVEMENTS
    # ========================================================

    "monthly_snapshots": TableSpecification(
        file_name="Monthly_Headcount_Snapshot.csv",
        required_columns=(
            "Snapshot_Month",
            "Department_ID",
            "Actual_Employee_Count",
            "Approved_Position_Count",
            "Budgeted_Position_Count",
            "Vacant_Approved_Position_Count",
            "Employees_Joining_During_Month",
            "Employees_Leaving_During_Month",
        ),
        date_columns=(
            "Snapshot_Month",
            "Data_As_Of_Date",
        ),
    ),

    "movements": TableSpecification(
        file_name="Workforce_Movement_History.csv",
        required_columns=(
            "Movement_ID",
            "Employee_ID",
            "Movement_Type",
            "Effective_Date",
        ),
        date_columns=(
            "Effective_Date",
        ),
    ),

    "historical_employees": TableSpecification(
    file_name="Historical_Employee_Register.csv",
    required_columns=(
        "Historical_Employee_ID",
        "Historical_Employee_Name",
        "Department_ID",
        "Department_Name",
        "Last_Known_Job_Level",
        "Historical_Status",
        "Record_Effective_Date",
    ),
    date_columns=(
        "Record_Effective_Date",
    ),
),
    # ========================================================
    # BUDGETS
    # ========================================================

    "department_budgets": TableSpecification(
        file_name="Department_Budget.csv",
        required_columns=(
            "Department_Budget_Record_ID",
            "Budget_Month",
            "Department_ID",
            "Total_Approved_People_Budget",
            "Total_Actual_People_Cost",
            "Remaining_People_Budget",
            "Budget_Utilization_Percentage",
        ),
        date_columns=(
            "Budget_Month",
            "Data_As_Of_Date",
        ),
    ),

    "position_budgets": TableSpecification(
        file_name="Position_Budget.csv",
        required_columns=(
            "Position_ID",
        ),
    ),

    # ========================================================
    # DAILY ACTIVITY AND EXCEPTIONS
    # ========================================================

    "daily_activity": TableSpecification(
        file_name="Daily_Headcount_Activity.csv",
        required_columns=(
            "Activity_Date",
            "Department_ID",
            "Actual_Employee_Count",
            "Employees_Available_for_Work",
            "Employees_on_Approved_Leave",
            "Employees_Absent",
            "Total_Overtime_Hours",
            "Workforce_Availability_Percentage",
        ),
        date_columns=(
            "Activity_Date",
            "Data_Refresh_Timestamp",
        ),
    ),

    "exceptions": TableSpecification(
        file_name="Headcount_Exception_Register.csv",
        required_columns=(
            "Exception_ID",
            "Department_ID",
            "Exception_Type",
            "Severity",
            "Metric_Name",
            "Current_Value",
            "Recommended_Action",
            "Exception_Status",
        ),
        date_columns=(
            "Detected_Date",
        ),
    ),

    # ========================================================
    # DEFINITIONS, RULES AND DEMAND
    # ========================================================

    "metric_definitions": TableSpecification(
        file_name="Headcount_Management_Metric_Definitions.csv",
        required_columns=(
            "Metric_Name",
            "Definition",
            "Calculation_Logic",
            "Primary_Source_Table",
        ),
    ),

    "rules": TableSpecification(
        file_name="Headcount_Management_Rules.csv",
        required_columns=(
            "Rule_ID",
        ),
    ),

    "demand_drivers": TableSpecification(
        file_name="Workforce_Demand_Drivers.csv",
        required_columns=(
            "Department_ID",
        ),
    ),
}


class HeadcountRepository:
    """Lazy, cached and read-only access to Headcount CSV tables."""

    def __init__(self, data_directory: str | Path) -> None:
        self.data_directory = Path(data_directory).expanduser().resolve()
        self._cache: dict[str, pd.DataFrame] = {}
        self._lock = RLock()

    # ========================================================
    # PUBLIC INFORMATION
    # ========================================================

    @property
    def available_table_names(self) -> tuple[str, ...]:
        """Return logical table names supported by this repository."""

        return tuple(TABLE_SPECIFICATIONS.keys())

    @property
    def loaded_table_names(self) -> tuple[str, ...]:
        """Return tables already loaded into memory."""

        with self._lock:
            return tuple(self._cache.keys())

    def file_path(self, table_name: str) -> Path:
        """Return the CSV path for a logical table name."""

        specification = self._get_specification(table_name)
        return self.data_directory / specification.file_name

    # ========================================================
    # TABLE ACCESS
    # ========================================================

    def get_table(
        self,
        table_name: str,
        *,
        copy: bool = True,
    ) -> pd.DataFrame:
        """Return one validated Headcount table.

        The file is loaded only on its first use. Later calls reuse the
        cached DataFrame.

        A deep copy is returned by default so services cannot accidentally
        modify the repository's cached source data.
        """

        specification = self._get_specification(table_name)

        with self._lock:
            if table_name not in self._cache:
                self._cache[table_name] = self._load_table(
                    table_name=table_name,
                    specification=specification,
                )

            dataframe = self._cache[table_name]

            return (
                dataframe.copy(deep=True)
                if copy
                else dataframe
            )

    def reload_table(self, table_name: str) -> pd.DataFrame:
        """Reload one table from disk and replace its cached copy."""

        specification = self._get_specification(table_name)

        with self._lock:
            dataframe = self._load_table(
                table_name=table_name,
                specification=specification,
            )

            self._cache[table_name] = dataframe

            return dataframe.copy(deep=True)

    def clear_cache(self) -> None:
        """Remove all cached DataFrames without changing any CSV file."""

        with self._lock:
            self._cache.clear()

    # ========================================================
    # HEALTH AND VALIDATION
    # ========================================================

    def health_report(self) -> pd.DataFrame:
        """Check whether supported files and required columns exist.

        This reads only CSV headers. It does not load all data into memory.
        """

        results: list[dict[str, object]] = []

        for table_name, specification in TABLE_SPECIFICATIONS.items():
            path = self.data_directory / specification.file_name

            if not path.is_file():
                results.append({
                    "Table_Name": table_name,
                    "File_Name": specification.file_name,
                    "Status": "MISSING_FILE",
                    "Missing_Columns": "",
                })
                continue

            try:
                header = pd.read_csv(
                    path,
                    nrows=0,
                    encoding="utf-8-sig",
                )

                missing_columns = sorted(
                    set(specification.required_columns)
                    - set(header.columns)
                )

                results.append({
                    "Table_Name": table_name,
                    "File_Name": specification.file_name,
                    "Status": (
                        "READY"
                        if not missing_columns
                        else "MISSING_COLUMNS"
                    ),
                    "Missing_Columns": ", ".join(
                        missing_columns
                    ),
                })

            except Exception as error:
                results.append({
                    "Table_Name": table_name,
                    "File_Name": specification.file_name,
                    "Status": "UNREADABLE",
                    "Missing_Columns": str(error),
                })

        return pd.DataFrame(results)

    def get_data_as_of_date(self) -> str | None:
        """Return the organization-level workforce reporting date."""

        organization = self.get_table("organization")

        if organization.empty:
            return None

        value = organization.loc[
            organization.index[0],
            "Workforce_Data_As_Of_Date",
        ]

        if pd.isna(value):
            return None

        if isinstance(value, pd.Timestamp):
            return value.date().isoformat()

        return str(value)

    # ========================================================
    # INTERNAL HELPERS
    # ========================================================

    def _get_specification(
        self,
        table_name: str,
    ) -> TableSpecification:
        try:
            return TABLE_SPECIFICATIONS[table_name]
        except KeyError as error:
            supported = ", ".join(
                sorted(TABLE_SPECIFICATIONS)
            )

            raise HeadcountDataError(
                f"Unknown Headcount table {table_name!r}. "
                f"Supported tables: {supported}"
            ) from error

    def _load_table(
        self,
        *,
        table_name: str,
        specification: TableSpecification,
    ) -> pd.DataFrame:
        path = self.data_directory / specification.file_name

        if not path.is_file():
            raise HeadcountDataError(
                f"Headcount file was not found: {path}"
            )

        try:
            dataframe = pd.read_csv(
                path,
                encoding="utf-8-sig",
                low_memory=False,
            )
        except Exception as error:
            raise HeadcountDataError(
                f"Could not read {specification.file_name}: "
                f"{error}"
            ) from error

        dataframe.columns = [
            str(column).strip()
            for column in dataframe.columns
        ]

        missing_columns = sorted(
            set(specification.required_columns)
            - set(dataframe.columns)
        )

        if missing_columns:
            raise HeadcountDataError(
                f"{specification.file_name} is missing required "
                f"columns: {', '.join(missing_columns)}"
            )

        # Normalize textual values while preserving missing values as <NA>.
        text_columns = dataframe.select_dtypes(
            include=["object", "string"]
        ).columns

        for column in text_columns:
            dataframe[column] = (
                dataframe[column]
                .astype("string")
                .str.strip()
            )

        # Parse only documented date columns.
        for column in specification.date_columns:
            if column in dataframe.columns:
                dataframe[column] = pd.to_datetime(
                    dataframe[column],
                    errors="coerce",
                )

        dataframe.attrs["logical_table_name"] = table_name
        dataframe.attrs["source_file"] = specification.file_name

        return dataframe