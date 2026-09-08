"""Read-only CSV repository for Headcount Management.

This module is completely separate from the existing Attrition and
successor pipelines. It only reads Headcount-related CSV files from
the shared Data directory.

Files are loaded lazily and cached after their first use.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
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

    def __init__(
        self,
        data_directory: str | Path,
        *,
        use_action_center_overlay: bool | None = None,
    ) -> None:
        self.data_directory = Path(data_directory).expanduser().resolve()
        self._cache: dict[str, pd.DataFrame] = {}
        self._lock = RLock()
        if use_action_center_overlay is None:
            use_action_center_overlay = os.getenv(
                "ACTION_CENTER_HEADCOUNT_OVERLAY",
                "false",
            ).strip().casefold() in {"1", "true", "yes", "on"}
        self.use_action_center_overlay = bool(use_action_center_overlay)
        self.action_center_overlay_path = (
            self.data_directory / "Employee_HR_Operational_State.csv"
        )
        self._overlay_last_error: str | None = None

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
                dataframe = self._load_table(
                    table_name=table_name,
                    specification=specification,
                )
                # The Action Center overlay is opt-in and read-time only.
                # It never writes the original Headcount CSVs.  If the overlay
                # is unavailable/invalid, the legacy table is returned exactly
                # as before so the existing application cannot be taken down
                # by the new operational module.
                if self.use_action_center_overlay:
                    try:
                        dataframe = self._apply_action_center_overlay(
                            table_name,
                            dataframe,
                        )
                        self._overlay_last_error = None
                    except Exception as error:  # fail open to legacy analytics
                        self._overlay_last_error = str(error)
                self._cache[table_name] = dataframe

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

    # ========================================================
    # OPTIONAL ACTION CENTER OPERATIONAL OVERLAY
    # ========================================================

    @property
    def action_center_overlay_status(self) -> dict[str, object]:
        """Describe the optional operational overlay without changing data."""

        return {
            "enabled": self.use_action_center_overlay,
            "file_exists": self.action_center_overlay_path.is_file(),
            "last_error": self._overlay_last_error,
        }

    def _apply_action_center_overlay(
        self,
        table_name: str,
        dataframe: pd.DataFrame,
    ) -> pd.DataFrame:
        """Apply current Action Center state to selected Headcount tables.

        This is intentionally an in-memory compatibility overlay.  It makes a
        confirmed resignation/transfer/promotion visible to the deterministic
        Headcount service immediately while preserving every legacy CSV byte on
        disk.  Before any Action Center action is applied, the overlay mirrors
        the original source values and therefore produces the same results.
        """

        if table_name not in {
            "employees",
            "assignments",
            "positions",
            "departments",
        }:
            return dataframe
        if not self.action_center_overlay_path.is_file():
            return dataframe

        state = pd.read_csv(
            self.action_center_overlay_path,
            encoding="utf-8-sig",
            keep_default_na=False,
            low_memory=False,
        )
        required = {
            "Employee_ID",
            "Employee_Status_Operational",
            "Operational_Department_ID",
            "Operational_Position_ID",
        }
        if not required.issubset(state.columns):
            return dataframe

        state.columns = [str(column).strip() for column in state.columns]
        if state["Employee_ID"].astype(str).str.upper().duplicated().any():
            raise HeadcountDataError(
                "Employee_HR_Operational_State.csv contains duplicate Employee_ID values."
            )

        if table_name == "employees":
            return self._overlay_employees(dataframe, state)
        if table_name == "assignments":
            return self._overlay_assignments(dataframe, state)
        if table_name == "positions":
            return self._overlay_positions(dataframe, state)
        if table_name == "departments":
            return self._overlay_departments(dataframe, state)
        return dataframe

    @staticmethod
    def _active_operational_state(state: pd.DataFrame) -> pd.DataFrame:
        status = (
            state["Employee_Status_Operational"]
            .astype("string")
            .str.strip()
            .str.casefold()
        )
        return state[
            status.isin({"active", "probation", "acting", "seconded"})
        ].copy()

    @staticmethod
    def _coalesce_overlay(
        frame: pd.DataFrame,
        state: pd.DataFrame,
        *,
        source_column: str,
        overlay_column: str,
    ) -> pd.DataFrame:
        if source_column not in frame.columns or overlay_column not in state.columns:
            return frame
        mapping = (
            state[["Employee_ID", overlay_column]]
            .drop_duplicates("Employee_ID")
            .set_index("Employee_ID")[overlay_column]
        )
        employee_key = frame["Employee_ID"].astype(str)
        overlay = employee_key.map(mapping)
        usable = overlay.notna() & overlay.astype(str).str.strip().ne("")
        frame.loc[usable, source_column] = overlay.loc[usable].values
        return frame

    def _overlay_employees(
        self,
        dataframe: pd.DataFrame,
        state: pd.DataFrame,
    ) -> pd.DataFrame:
        frame = dataframe.copy()
        active = self._active_operational_state(state)
        active_ids = set(active["Employee_ID"].astype(str).str.upper())
        frame = frame[
            frame["Employee_ID"].astype(str).str.upper().isin(active_ids)
        ].copy()

        column_map = {
            "Employee_Status": "Employee_Status_Operational",
            "Department_ID": "Operational_Department_ID",
            "Department": "Operational_Department_Name",
            "Business_Unit": "Operational_Business_Unit",
            "Organizational_Unit_ID": "Operational_Organizational_Unit_ID",
            "Work_Location_ID": "Operational_Work_Location_ID",
            "Position_ID": "Operational_Position_ID",
            "Position_Title": "Operational_Position_Title",
            "Job_Level": "Operational_Job_Level",
            "Employment_Type": "Operational_Employment_Type",
            "Manager_Employee_ID": "Operational_Manager_Employee_ID",
        }
        for source, overlay in column_map.items():
            frame = self._coalesce_overlay(
                frame,
                active,
                source_column=source,
                overlay_column=overlay,
            )
        frame.attrs.update(dataframe.attrs)
        frame.attrs["action_center_overlay"] = True
        return frame

    def _overlay_assignments(
        self,
        dataframe: pd.DataFrame,
        state: pd.DataFrame,
    ) -> pd.DataFrame:
        frame = dataframe.copy()
        active = self._active_operational_state(state)
        active_ids = set(active["Employee_ID"].astype(str).str.upper())
        current_mask = (
            frame["Assignment_Status"]
            .astype("string")
            .str.casefold()
            .eq("current")
        )
        employee_ids = frame["Employee_ID"].astype(str).str.upper()
        ended = current_mask & ~employee_ids.isin(active_ids)
        frame.loc[ended, "Assignment_Status"] = "Ended"
        if "Assignment_End_Date" in frame.columns:
            updated_at = (
                state[["Employee_ID", "Operational_State_Updated_At"]]
                .drop_duplicates("Employee_ID")
                .set_index("Employee_ID")["Operational_State_Updated_At"]
                if "Operational_State_Updated_At" in state.columns
                else pd.Series(dtype="object")
            )
            end_values = frame.loc[ended, "Employee_ID"].astype(str).map(updated_at)
            parsed = pd.to_datetime(end_values, errors="coerce")
            frame.loc[ended, "Assignment_End_Date"] = parsed.values

        active_rows = current_mask & employee_ids.isin(active_ids)
        subset = frame.loc[active_rows].copy()
        column_map = {
            "Position_ID": "Operational_Position_ID",
            "Position_Title": "Operational_Position_Title",
            "Department_ID": "Operational_Department_ID",
            "Department_Name": "Operational_Department_Name",
            "Business_Unit": "Operational_Business_Unit",
            "Organizational_Unit_ID": "Operational_Organizational_Unit_ID",
            "Work_Location_ID": "Operational_Work_Location_ID",
            "Manager_Employee_ID": "Operational_Manager_Employee_ID",
            "Employment_Type": "Operational_Employment_Type",
        }
        for source, overlay in column_map.items():
            subset = self._coalesce_overlay(
                subset,
                active,
                source_column=source,
                overlay_column=overlay,
            )

        # Keep assignment cost center aligned to the selected operational
        # position when the employee moves between departments/positions.
        if not subset.empty and "Cost_Center_ID" in subset.columns:
            positions = pd.read_csv(
                self.data_directory / "Position_Master.csv",
                encoding="utf-8-sig",
                keep_default_na=False,
                low_memory=False,
            )
            pos_cost = (
                positions[["Position_ID", "Cost_Center_ID"]]
                .drop_duplicates("Position_ID")
                .set_index("Position_ID")["Cost_Center_ID"]
            )
            mapped = subset["Position_ID"].astype(str).map(pos_cost)
            good = mapped.astype(str).str.strip().ne("")
            subset.loc[good, "Cost_Center_ID"] = mapped.loc[good].values

        frame.loc[active_rows, subset.columns] = subset.values
        frame.attrs.update(dataframe.attrs)
        frame.attrs["action_center_overlay"] = True
        return frame

    def _overlay_positions(
        self,
        dataframe: pd.DataFrame,
        state: pd.DataFrame,
    ) -> pd.DataFrame:
        frame = dataframe.copy()
        active = self._active_operational_state(state)
        active = active[
            active["Operational_Position_ID"].astype(str).str.strip().ne("")
        ].copy()
        dupes = (
            active["Operational_Position_ID"]
            .astype(str)
            .str.upper()
            .duplicated(keep=False)
        )
        if dupes.any():
            ids = sorted(
                active.loc[dupes, "Operational_Position_ID"]
                .astype(str)
                .str.upper()
                .unique()
                .tolist()
            )
            raise HeadcountDataError(
                "Action Center operational state assigns multiple active employees "
                "to the same position: " + ", ".join(ids[:10])
            )

        occupant = {
            str(row["Operational_Position_ID"]).upper(): (
                str(row["Employee_ID"]),
                str(row.get("Employee_Name", "")),
                str(row.get("Operational_State_Updated_At", "")),
            )
            for _, row in active.iterrows()
        }

        for index, row in frame.iterrows():
            position_id = str(row.get("Position_ID", "")).upper()
            freeze_status = str(row.get("Position_Freeze_Status", "")).casefold()
            source_status = str(row.get("Position_Status", "")).casefold()
            person = occupant.get(position_id)
            if person:
                frame.at[index, "Position_Status"] = "Filled"
                frame.at[index, "Current_Employee_ID"] = person[0]
                frame.at[index, "Current_Employee_Name"] = person[1]
                if "Vacancy_Start_Date" in frame.columns:
                    frame.at[index, "Vacancy_Start_Date"] = pd.NaT
            elif freeze_status == "frozen" or source_status == "frozen":
                frame.at[index, "Position_Status"] = "Frozen"
                frame.at[index, "Current_Employee_ID"] = pd.NA
                frame.at[index, "Current_Employee_Name"] = pd.NA
            else:
                became_vacant = source_status == "filled"
                frame.at[index, "Position_Status"] = "Vacant"
                frame.at[index, "Current_Employee_ID"] = pd.NA
                frame.at[index, "Current_Employee_Name"] = pd.NA
                if became_vacant and "Vacancy_Start_Date" in frame.columns:
                    # Use the former source occupant's operational update time
                    # when available; otherwise current UTC date is a safe
                    # reporting fallback for the read-time overlay.
                    former = str(row.get("Current_Employee_ID", ""))
                    change_map = (
                        state[["Employee_ID", "Operational_State_Updated_At"]]
                        .drop_duplicates("Employee_ID")
                        .set_index("Employee_ID")["Operational_State_Updated_At"]
                        if "Operational_State_Updated_At" in state.columns
                        else pd.Series(dtype="object")
                    )
                    changed = change_map.get(former, "") if former else ""
                    parsed = pd.to_datetime(changed, errors="coerce", utc=True)
                    if not pd.isna(parsed):
                        parsed = parsed.tz_localize(None)
                    frame.at[index, "Vacancy_Start_Date"] = (
                        parsed if not pd.isna(parsed) else pd.Timestamp.utcnow().tz_localize(None).normalize()
                    )

        frame.attrs.update(dataframe.attrs)
        frame.attrs["action_center_overlay"] = True
        return frame

    def _overlay_departments(
        self,
        dataframe: pd.DataFrame,
        state: pd.DataFrame,
    ) -> pd.DataFrame:
        frame = dataframe.copy()
        active = self._active_operational_state(state)
        counts = (
            active.groupby("Operational_Department_ID")["Employee_ID"]
            .nunique()
            .to_dict()
        )
        if "Current_Employee_Count" in frame.columns:
            frame["Current_Employee_Count"] = (
                frame["Department_ID"].astype(str).map(counts).fillna(0).astype(int)
            )
        frame.attrs.update(dataframe.attrs)
        frame.attrs["action_center_overlay"] = True
        return frame

    def _overlay_current_summary(
        self,
        dataframe: pd.DataFrame,
        state: pd.DataFrame,
    ) -> pd.DataFrame:
        frame = dataframe.copy()
        active = self._active_operational_state(state)
        actual = (
            active.groupby("Operational_Department_ID")["Employee_ID"]
            .nunique()
            .to_dict()
        )
        positions = self._overlay_positions(
            self._load_table(
                table_name="positions",
                specification=TABLE_SPECIFICATIONS["positions"],
            ),
            state,
        )
        approved = positions["Approved_Position"].astype(str).str.casefold().eq("yes")
        budgeted = positions["Budgeted_Position"].astype(str).str.casefold().eq("yes")
        open_status = positions["Position_Status"].astype(str).str.casefold().isin({"vacant", "frozen"})
        tmp = positions.assign(
            _approved=approved.astype(int),
            _budgeted=budgeted.astype(int),
            _vacant_approved=(approved & open_status).astype(int),
            _funded_vacant=(budgeted & open_status).astype(int),
        )
        sums = tmp.groupby("Department_ID").agg(
            Approved_Position_Count=("_approved", "sum"),
            Budgeted_Position_Count=("_budgeted", "sum"),
            Vacant_Approved_Position_Count=("_vacant_approved", "sum"),
            Funded_Vacant_Position_Count=("_funded_vacant", "sum"),
        )
        total_row_indexes: list[int] = []
        department_overstaffed = 0
        for index, row in frame.iterrows():
            dept = str(row.get("Department_ID", ""))
            if dept.strip().upper() in {"ORGANIZATION-TOTAL", "ORGANISATION-TOTAL", "TOTAL"}:
                total_row_indexes.append(index)
                continue
            current = int(actual.get(dept, 0))
            frame.at[index, "Actual_Employee_Count"] = current
            if dept in sums.index:
                for column in sums.columns:
                    if column in frame.columns:
                        frame.at[index, column] = int(sums.at[dept, column])
            approved_count = float(frame.at[index, "Approved_Position_Count"] or 0)
            vacancy = float(frame.at[index, "Vacant_Approved_Position_Count"] or 0)
            overstaffed = max(0, current - int(approved_count))
            department_overstaffed += overstaffed
            if "Overstaffed_Employee_Count" in frame.columns:
                frame.at[index, "Overstaffed_Employee_Count"] = overstaffed
            if "Vacancy_Rate_Percentage" in frame.columns:
                frame.at[index, "Vacancy_Rate_Percentage"] = (
                    round((vacancy / approved_count) * 100.0, 2)
                    if approved_count
                    else 0.0
                )

        # Preserve the reference file's organization-total row semantics while
        # making the few headcount-derived values operationally current.
        for index in total_row_indexes:
            current = int(len(active))
            frame.at[index, "Actual_Employee_Count"] = current
            for column in sums.columns:
                if column in frame.columns:
                    frame.at[index, column] = int(sums[column].sum())
            if "Overstaffed_Employee_Count" in frame.columns:
                frame.at[index, "Overstaffed_Employee_Count"] = department_overstaffed
            approved_count = float(frame.at[index, "Approved_Position_Count"] or 0)
            vacancy = float(frame.at[index, "Vacant_Approved_Position_Count"] or 0)
            if "Vacancy_Rate_Percentage" in frame.columns:
                frame.at[index, "Vacancy_Rate_Percentage"] = (
                    round((vacancy / approved_count) * 100.0, 2)
                    if approved_count
                    else 0.0
                )
        frame.attrs.update(dataframe.attrs)
        frame.attrs["action_center_overlay"] = True
        return frame

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