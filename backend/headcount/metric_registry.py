"""Safe metric and dimension registry for Headcount Management.

This registry provides the controlled vocabulary used by the future
Headcount query planner and deterministic calculation service.

It does not execute pandas operations, call an LLM, or modify the
existing Attrition pipeline.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from collections.abc import Mapping
from typing import Final


# ============================================================
# DEFINITIONS
# ============================================================

@dataclass(frozen=True)
class MetricDefinition:
    """Metadata describing one supported Headcount metric."""

    name: str
    display_name: str
    category: str
    unit: str
    description: str

    # Logical table names from HeadcountRepository.
    source_tables: tuple[str, ...]

    # Default deterministic operation used by the future service.
    operation: str

    # Direct source column, where applicable.
    source_column: str | None = None

    # Safe human-readable formula for derived metrics.
    formula: str | None = None

    # Conditions that must be applied before calculation.
    # Each tuple contains:
    # (column_name, operator, value)
    filters: tuple[tuple[str, str, object], ...] = ()

    # Historical source, where available.
    historical_table: str | None = None
    historical_column: str | None = None

    # Alternative phrases the LLM or user may use.
    aliases: tuple[str, ...] = ()

    # Some metrics require another existing service.
    external_dependency: bool = False


@dataclass(frozen=True)
class DimensionDefinition:
    """Metadata describing one filter or grouping dimension."""

    name: str
    display_name: str
    description: str

    # Pairs of:
    # (logical repository table name, CSV column name)
    source_columns: tuple[tuple[str, str], ...]

    aliases: tuple[str, ...] = ()

    def column_for(self, table_name: str) -> str | None:
        """Return the dimension column for a repository table."""

        for source_table, source_column in self.source_columns:
            if source_table == table_name:
                return source_column

        return None


# ============================================================
# METRIC REGISTRY
# ============================================================

METRICS: Final[dict[str, MetricDefinition]] = {
    # --------------------------------------------------------
    # CURRENT HEADCOUNT
    # --------------------------------------------------------

    "actual_employee_count": MetricDefinition(
        name="actual_employee_count",
        display_name="Actual Employee Count",
        category="headcount",
        unit="employees",
        description=(
            "Count of employees with a current assignment."
        ),
        source_tables=("assignments",),
        operation="count_distinct",
        source_column="Employee_ID",
        filters=(
            (
                "Assignment_Status",
                "equals",
                "Current",
            ),
        ),
        historical_table="monthly_snapshots",
        historical_column="Actual_Employee_Count",
        aliases=(
            "actual headcount",
            "current headcount",
            "employee count",
            "number of employees",
            "current employees",
            "total employees",
            "workforce count",
            "workforce size",
        ),
    ),

    "approved_position_count": MetricDefinition(
        name="approved_position_count",
        display_name="Approved Position Count",
        category="positions",
        unit="positions",
        description=(
            "Count of positions authorized in the approved "
            "organizational establishment."
        ),
        source_tables=("positions",),
        operation="count_distinct",
        source_column="Position_ID",
        filters=(
            (
                "Approved_Position",
                "equals",
                "Yes",
            ),
        ),
        historical_table="monthly_snapshots",
        historical_column="Approved_Position_Count",
        aliases=(
            "approved headcount",
            "approved positions",
            "authorized headcount",
            "authorized positions",
            "approved establishment",
        ),
    ),

    "budgeted_position_count": MetricDefinition(
        name="budgeted_position_count",
        display_name="Budgeted Position Count",
        category="positions",
        unit="positions",
        description=(
            "Count of positions for which people budget is available."
        ),
        source_tables=("positions",),
        operation="count_distinct",
        source_column="Position_ID",
        filters=(
            (
                "Budgeted_Position",
                "equals",
                "Yes",
            ),
        ),
        historical_table="monthly_snapshots",
        historical_column="Budgeted_Position_Count",
        aliases=(
            "budgeted headcount",
            "budgeted positions",
            "funded headcount",
            "funded positions",
        ),
    ),

    "filled_position_count": MetricDefinition(
        name="filled_position_count",
        display_name="Filled Position Count",
        category="positions",
        unit="positions",
        description=(
            "Count of positions currently occupied by employees."
        ),
        source_tables=("positions",),
        operation="count_distinct",
        source_column="Position_ID",
        filters=(
            (
                "Position_Status",
                "equals",
                "Filled",
            ),
        ),
        aliases=(
            "filled positions",
            "occupied positions",
            "positions filled",
        ),
    ),

    "vacant_position_count": MetricDefinition(
        name="vacant_position_count",
        display_name="Vacant Position Count",
        category="vacancies",
        unit="positions",
        description=(
            "Count of positions whose current status is Vacant."
        ),
        source_tables=("positions",),
        operation="count_distinct",
        source_column="Position_ID",
        filters=(
            (
                "Position_Status",
                "equals",
                "Vacant",
            ),
        ),
        aliases=(
            "vacant positions",
            "vacancies",
            "open positions",
            "empty positions",
        ),
    ),

    "frozen_position_count": MetricDefinition(
        name="frozen_position_count",
        display_name="Frozen Position Count",
        category="vacancies",
        unit="positions",
        description=(
            "Count of positions currently frozen for hiring."
        ),
        source_tables=("positions",),
        operation="count_distinct",
        source_column="Position_ID",
        filters=(
            (
                "Position_Status",
                "equals",
                "Frozen",
            ),
        ),
        aliases=(
            "frozen positions",
            "positions on freeze",
            "hiring freeze positions",
        ),
    ),

    "vacant_approved_position_count": MetricDefinition(
        name="vacant_approved_position_count",
        display_name="Vacant Approved Position Count",
        category="vacancies",
        unit="positions",
        description=(
            "Approved positions that do not currently have an "
            "employee assignment."
        ),
        source_tables=(
            "positions",
            "assignments",
        ),
        operation="derived",
        formula=(
            "approved_position_count - "
            "filled_approved_position_count"
        ),
        historical_table="monthly_snapshots",
        historical_column="Vacant_Approved_Position_Count",
        aliases=(
            "approved vacancies",
            "vacant approved positions",
            "approved open positions",
        ),
    ),

    "funded_vacant_position_count": MetricDefinition(
        name="funded_vacant_position_count",
        display_name="Funded Vacant Position Count",
        category="vacancies",
        unit="positions",
        description=(
            "Budgeted positions that are currently vacant or frozen."
        ),
        source_tables=("positions",),
        operation="count_distinct",
        source_column="Position_ID",
        filters=(
            (
                "Budgeted_Position",
                "equals",
                "Yes",
            ),
            (
                "Position_Status",
                "in",
                ("Vacant", "Frozen"),
            ),
        ),
        historical_table="monthly_snapshots",
        historical_column="Funded_Vacant_Position_Count",
        aliases=(
            "funded vacancies",
            "budgeted vacancies",
            "vacancies with budget",
            "open funded positions",
        ),
    ),

    "unfunded_vacant_position_count": MetricDefinition(
        name="unfunded_vacant_position_count",
        display_name="Unfunded Vacant Position Count",
        category="vacancies",
        unit="positions",
        description=(
            "Approved vacant or frozen positions without available "
            "position budget."
        ),
        source_tables=("positions",),
        operation="count_distinct",
        source_column="Position_ID",
        filters=(
            (
                "Approved_Position",
                "equals",
                "Yes",
            ),
            (
                "Budgeted_Position",
                "equals",
                "No",
            ),
            (
                "Position_Status",
                "in",
                ("Vacant", "Frozen"),
            ),
        ),
        aliases=(
            "unfunded vacancies",
            "vacancies without budget",
            "non budgeted vacancies",
        ),
    ),

    "headcount_variance": MetricDefinition(
        name="headcount_variance",
        display_name="Headcount Variance",
        category="headcount",
        unit="employees",
        description=(
            "Difference between actual employees and approved "
            "positions."
        ),
        source_tables=(
            "assignments",
            "positions",
        ),
        operation="derived",
        formula=(
            "actual_employee_count - approved_position_count"
        ),
        historical_table="monthly_snapshots",
        aliases=(
            "headcount gap",
            "staffing variance",
            "actual versus approved",
            "actual vs approved",
            "staffing gap",
        ),
    ),
    "net_approved_headcount_gap": MetricDefinition(
    name="net_approved_headcount_gap",
    display_name="Net Approved Headcount Gap",
    category="headcount",
    unit="positions",
    description=(
        "Difference between approved positions and actual "
        "employee count. A positive value means understaffing, "
        "while a negative value means overstaffing."
    ),
    source_tables=(
        "positions",
        "assignments",
    ),
    operation="derived",
    formula=(
        "approved_position_count - actual_employee_count"
    ),
    historical_table="monthly_snapshots",
    aliases=(
        "net approved gap",
        "approved headcount gap",
        "net staffing gap",
        "approved staffing gap",
        "approved positions minus employees",
    ),
),

"net_budgeted_headcount_gap": MetricDefinition(
    name="net_budgeted_headcount_gap",
    display_name="Net Budgeted Headcount Gap",
    category="headcount",
    unit="positions",
    description=(
        "Difference between budgeted positions and actual "
        "employee count. A positive value means funded staffing "
        "capacity remains available."
    ),
    source_tables=(
        "positions",
        "assignments",
    ),
    operation="derived",
    formula=(
        "budgeted_position_count - actual_employee_count"
    ),
    historical_table="monthly_snapshots",
    aliases=(
        "net budgeted gap",
        "budgeted headcount gap",
        "funded staffing gap",
        "budgeted positions minus employees",
    ),
),
    "vacancy_rate_percentage": MetricDefinition(
        name="vacancy_rate_percentage",
        display_name="Vacancy Rate",
        category="vacancies",
        unit="percentage",
        description=(
            "Vacant approved positions as a percentage of approved "
            "positions."
        ),
        source_tables=(
            "positions",
            "assignments",
        ),
        operation="derived",
        formula=(
            "vacant_approved_position_count / "
            "approved_position_count * 100"
        ),
        historical_table="monthly_snapshots",
        historical_column="Vacancy_Rate_Percentage",
        aliases=(
            "vacancy rate",
            "vacancy percentage",
            "open position rate",
            "position vacancy rate",
        ),
    ),

    "headcount_utilization_percentage": MetricDefinition(
        name="headcount_utilization_percentage",
        display_name="Headcount Utilization",
        category="headcount",
        unit="percentage",
        description=(
            "Actual employee count as a percentage of approved "
            "positions."
        ),
        source_tables=(
            "assignments",
            "positions",
        ),
        operation="derived",
        formula=(
            "actual_employee_count / "
            "approved_position_count * 100"
        ),
        aliases=(
            "headcount utilization",
            "staffing utilization",
            "position fill percentage",
            "approved headcount utilization",
        ),
    ),

    "actual_full_time_equivalent": MetricDefinition(
        name="actual_full_time_equivalent",
        display_name="Actual Full-Time Equivalent",
        category="headcount",
        unit="FTE",
        description=(
            "Sum of assignment capacity for current employee "
            "assignments."
        ),
        source_tables=("assignments",),
        operation="sum",
        source_column="Assignment_Full_Time_Equivalent",
        filters=(
            (
                "Assignment_Status",
                "equals",
                "Current",
            ),
        ),
        historical_table="monthly_snapshots",
        historical_column="Actual_Full_Time_Equivalent",
        aliases=(
            "actual fte",
            "current fte",
            "full time equivalent",
            "fte count",
        ),
    ),

    "overstaffed_employee_count": MetricDefinition(
        name="overstaffed_employee_count",
        display_name="Overstaffed Employee Count",
        category="headcount",
        unit="employees",
        description=(
            "Number of employees above the approved position count."
        ),
        source_tables=(
            "assignments",
            "positions",
        ),
        operation="derived",
        formula=(
            "max(actual_employee_count - "
            "approved_position_count, 0)"
        ),
        historical_table="monthly_snapshots",
        historical_column="Overstaffed_Employee_Count",
        aliases=(
            "overstaffed employees",
            "excess employees",
            "above approved headcount",
            "over establishment",
        ),
    ),
    "included_in_approved_headcount_count": MetricDefinition(
        name="included_in_approved_headcount_count",
        display_name=(
            "Employees Included in Approved Headcount"
        ),
        category="headcount",
        unit="employees",
        description=(
            "Count of current employees included in the "
            "approved Headcount establishment."
        ),
        source_tables=("employees",),
        operation="count_distinct",
        source_column="Employee_ID",
        filters=(
            (
                "Included_in_Approved_Headcount",
                "equals",
                "Yes",
            ),
        ),
        aliases=(
            "employees included in approved headcount",
            "included employee count",
            "approved headcount included employees",
        ),
    ),

    "excluded_from_approved_headcount_count": MetricDefinition(
        name="excluded_from_approved_headcount_count",
        display_name=(
            "Employees Excluded from Approved Headcount"
        ),
        category="headcount",
        unit="employees",
        description=(
            "Count of current employees not included in the "
            "approved Headcount establishment."
        ),
        source_tables=("employees",),
        operation="count_distinct",
        source_column="Employee_ID",
        filters=(
            (
                "Included_in_Approved_Headcount",
                "equals",
                "No",
            ),
        ),
        aliases=(
            "employees excluded from approved headcount",
            "excluded employee count",
            "employees outside approved headcount",
        ),
    ),

    "approved_headcount_inclusion_percentage": MetricDefinition(
        name="approved_headcount_inclusion_percentage",
        display_name="Approved Headcount Inclusion",
        category="headcount",
        unit="percentage",
        description=(
            "Percentage of current employees included in "
            "approved Headcount."
        ),
        source_tables=("employees",),
        operation="derived",
        formula=(
            "included_in_approved_headcount_count / "
            "actual_employee_count * 100"
        ),
        aliases=(
            "approved headcount inclusion percentage",
            "headcount inclusion percentage",
            "headcount inclusion rate",
        ),
    ),

    "average_tenure_months": MetricDefinition(
        name="average_tenure_months",
        display_name="Average Employee Tenure",
        category="headcount",
        unit="months",
        description=(
            "Average employee tenure in months for the "
            "selected workforce."
        ),
        source_tables=("employees",),
        operation="average",
        source_column="Tenure_Months",
        aliases=(
            "average tenure",
            "average employee tenure",
            "mean tenure",
        ),
    ),

    "average_years_in_company": MetricDefinition(
        name="average_years_in_company",
        display_name="Average Years in Company",
        category="headcount",
        unit="years",
        description=(
            "Average years employees have worked in the company."
        ),
        source_tables=("employees",),
        operation="average",
        source_column="Years_in_Company",
        aliases=(
            "average years in company",
            "average service years",
            "mean years in company",
        ),
    ),
    # --------------------------------------------------------
    # BUDGET METRICS
    # --------------------------------------------------------

    "total_approved_people_budget": MetricDefinition(
        name="total_approved_people_budget",
        display_name="Total Approved People Budget",
        category="budget",
        unit="PKR",
        description=(
            "Total approved workforce-related budget."
        ),
        source_tables=("department_budgets",),
        operation="sum",
        source_column="Total_Approved_People_Budget",
        historical_table="department_budgets",
        historical_column="Total_Approved_People_Budget",
        aliases=(
            "approved people budget",
            "headcount budget",
            "workforce budget",
            "total people budget",
        ),
    ),

    "total_actual_people_cost": MetricDefinition(
        name="total_actual_people_cost",
        display_name="Total Actual People Cost",
        category="budget",
        unit="PKR",
        description=(
            "Total salary, benefits, recruitment, training and "
            "overtime cost incurred."
        ),
        source_tables=("department_budgets",),
        operation="sum",
        source_column="Total_Actual_People_Cost",
        historical_table="department_budgets",
        historical_column="Total_Actual_People_Cost",
        aliases=(
            "actual people cost",
            "workforce cost",
            "employee cost",
            "actual headcount cost",
        ),
    ),

    "remaining_people_budget": MetricDefinition(
        name="remaining_people_budget",
        display_name="Remaining People Budget",
        category="budget",
        unit="PKR",
        description=(
            "Approved people budget remaining after actual people "
            "cost."
        ),
        source_tables=("department_budgets",),
        operation="sum",
        source_column="Remaining_People_Budget",
        historical_table="department_budgets",
        historical_column="Remaining_People_Budget",
        aliases=(
            "remaining budget",
            "available people budget",
            "unused workforce budget",
            "budget remaining",
        ),
    ),

    "budget_utilization_percentage": MetricDefinition(
        name="budget_utilization_percentage",
        display_name="Budget Utilization",
        category="budget",
        unit="percentage",
        description=(
            "Actual people cost as a percentage of approved "
            "people budget."
        ),
        source_tables=("department_budgets",),
        operation="derived",
        formula=(
            "total_actual_people_cost / "
            "total_approved_people_budget * 100"
        ),
        historical_table="department_budgets",
        historical_column="Budget_Utilization_Percentage",
        aliases=(
            "budget utilization",
            "budget usage",
            "people budget consumption",
            "budget consumed",
            "budget utilization rate",
        ),
    ),
    "approved_salary_and_benefits_budget": MetricDefinition(
        name="approved_salary_and_benefits_budget",
        display_name="Approved Salary and Benefits Budget",
        category="budget",
        unit="PKR",
        description=(
            "Approved budget for employee salaries and benefits."
        ),
        source_tables=("department_budgets",),
        operation="sum",
        source_column=(
            "Approved_Salary_and_Benefits_Budget"
        ),
        historical_table="department_budgets",
        historical_column=(
            "Approved_Salary_and_Benefits_Budget"
        ),
        aliases=(
            "salary and benefits budget",
            "approved salary budget",
            "compensation budget",
        ),
    ),

    "recruitment_budget": MetricDefinition(
        name="recruitment_budget",
        display_name="Recruitment Budget",
        category="budget",
        unit="PKR",
        description=(
            "Approved budget for employee recruitment."
        ),
        source_tables=("department_budgets",),
        operation="sum",
        source_column="Recruitment_Budget",
        historical_table="department_budgets",
        historical_column="Recruitment_Budget",
        aliases=(
            "hiring budget",
            "recruiting budget",
        ),
    ),

    "training_and_development_budget": MetricDefinition(
        name="training_and_development_budget",
        display_name="Training and Development Budget",
        category="budget",
        unit="PKR",
        description=(
            "Approved budget for employee training and development."
        ),
        source_tables=("department_budgets",),
        operation="sum",
        source_column=(
            "Training_and_Development_Budget"
        ),
        historical_table="department_budgets",
        historical_column=(
            "Training_and_Development_Budget"
        ),
        aliases=(
            "training budget",
            "development budget",
            "learning budget",
        ),
    ),

    "overtime_budget": MetricDefinition(
        name="overtime_budget",
        display_name="Overtime Budget",
        category="budget",
        unit="PKR",
        description=(
            "Approved workforce overtime budget."
        ),
        source_tables=("department_budgets",),
        operation="sum",
        source_column="Overtime_Budget",
        historical_table="department_budgets",
        historical_column="Overtime_Budget",
        aliases=(
            "approved overtime budget",
            "overtime allocation",
        ),
    ),

    "workforce_contingency_budget": MetricDefinition(
        name="workforce_contingency_budget",
        display_name="Workforce Contingency Budget",
        category="budget",
        unit="PKR",
        description=(
            "Approved budget reserved for unplanned workforce costs."
        ),
        source_tables=("department_budgets",),
        operation="sum",
        source_column="Workforce_Contingency_Budget",
        historical_table="department_budgets",
        historical_column="Workforce_Contingency_Budget",
        aliases=(
            "contingency budget",
            "workforce reserve budget",
        ),
    ),

    "actual_salary_cost": MetricDefinition(
        name="actual_salary_cost",
        display_name="Actual Salary Cost",
        category="budget",
        unit="PKR",
        description=(
            "Actual salary cost incurred during the reporting period."
        ),
        source_tables=("department_budgets",),
        operation="sum",
        source_column="Actual_Salary_Cost",
        historical_table="department_budgets",
        historical_column="Actual_Salary_Cost",
        aliases=(
            "salary cost",
            "actual salaries",
            "payroll salary cost",
        ),
    ),

    "actual_benefits_cost": MetricDefinition(
        name="actual_benefits_cost",
        display_name="Actual Benefits Cost",
        category="budget",
        unit="PKR",
        description=(
            "Actual employee-benefits cost incurred."
        ),
        source_tables=("department_budgets",),
        operation="sum",
        source_column="Actual_Benefits_Cost",
        historical_table="department_budgets",
        historical_column="Actual_Benefits_Cost",
        aliases=(
            "benefits cost",
            "employee benefits cost",
        ),
    ),

    "actual_recruitment_cost": MetricDefinition(
        name="actual_recruitment_cost",
        display_name="Actual Recruitment Cost",
        category="budget",
        unit="PKR",
        description=(
            "Actual employee-recruitment cost incurred."
        ),
        source_tables=("department_budgets",),
        operation="sum",
        source_column="Actual_Recruitment_Cost",
        historical_table="department_budgets",
        historical_column="Actual_Recruitment_Cost",
        aliases=(
            "recruitment cost",
            "hiring cost",
            "actual hiring cost",
        ),
    ),

    "actual_training_cost": MetricDefinition(
        name="actual_training_cost",
        display_name="Actual Training Cost",
        category="budget",
        unit="PKR",
        description=(
            "Actual employee training and development cost."
        ),
        source_tables=("department_budgets",),
        operation="sum",
        source_column="Actual_Training_Cost",
        historical_table="department_budgets",
        historical_column="Actual_Training_Cost",
        aliases=(
            "training cost",
            "learning cost",
            "development cost",
        ),
    ),

    "actual_overtime_cost": MetricDefinition(
        name="actual_overtime_cost",
        display_name="Actual Overtime Cost",
        category="budget",
        unit="PKR",
        description=(
            "Actual employee-overtime cost incurred."
        ),
        source_tables=("department_budgets",),
        operation="sum",
        source_column="Actual_Overtime_Cost",
        historical_table="department_budgets",
        historical_column="Actual_Overtime_Cost",
        aliases=(
            "overtime cost",
            "actual overtime expense",
        ),
    ),
    # --------------------------------------------------------
    # MOVEMENT METRICS
    # --------------------------------------------------------

    "joiner_count": MetricDefinition(
        name="joiner_count",
        display_name="Joiner Count",
        category="movement",
        unit="employees",
        description="Count of employees joining the organization.",
        source_tables=("movements",),
        operation="count_distinct",
        source_column="Movement_ID",
        filters=(
            (
                "Movement_Type",
                "equals",
                "Join",
            ),
        ),
        historical_table="monthly_snapshots",
        historical_column="Employees_Joining_During_Month",
        aliases=(
            "joiners",
            "new hires",
            "employees joined",
            "new employees",
            "hires",
        ),
    ),

    "leaver_count": MetricDefinition(
        name="leaver_count",
        display_name="Leaver Count",
        category="movement",
        unit="employees",
        description="Count of employees leaving the organization.",
        source_tables=("movements",),
        operation="count_distinct",
        source_column="Movement_ID",
        filters=(
            (
                "Movement_Type",
                "equals",
                "Leave",
            ),
        ),
        historical_table="monthly_snapshots",
        historical_column="Employees_Leaving_During_Month",
        aliases=(
            "leavers",
            "employees left",
            "employee exits",
            "departures",
        ),
    ),

    "promotion_count": MetricDefinition(
        name="promotion_count",
        display_name="Promotion Count",
        category="movement",
        unit="employees",
        description="Count of recorded employee promotions.",
        source_tables=("movements",),
        operation="count_distinct",
        source_column="Movement_ID",
        filters=(
            (
                "Movement_Type",
                "equals",
                "Promotion",
            ),
        ),
        historical_table="monthly_snapshots",
        historical_column="Employees_Promoted",
        aliases=(
            "promotions",
            "employees promoted",
            "promotion movements",
        ),
    ),

    "transfer_count": MetricDefinition(
        name="transfer_count",
        display_name="Transfer Count",
        category="movement",
        unit="employees",
        description="Count of recorded employee transfers.",
        source_tables=("movements",),
        operation="count_distinct",
        source_column="Movement_ID",
        filters=(
            (
                "Movement_Type",
                "equals",
                "Transfer",
            ),
        ),
        aliases=(
            "transfers",
            "employee transfers",
            "internal transfers",
        ),
    ),
    "transfer_in_count": MetricDefinition(
        name="transfer_in_count",
        display_name="Transfer-In Count",
        category="movement",
        unit="employees",
        description=(
            "Count of employees transferred into a department."
        ),
        source_tables=("movements",),
        operation="count_distinct",
        source_column="Movement_ID",
        filters=(
            (
                "Movement_Type",
                "equals",
                "Transfer",
            ),
        ),
        historical_table="monthly_snapshots",
        historical_column="Employees_Transferred_In",
        aliases=(
            "transfers in",
            "employees transferred in",
            "incoming transfers",
            "transfer inflow",
        ),
    ),

    "transfer_out_count": MetricDefinition(
        name="transfer_out_count",
        display_name="Transfer-Out Count",
        category="movement",
        unit="employees",
        description=(
            "Count of employees transferred out of a department."
        ),
        source_tables=("movements",),
        operation="count_distinct",
        source_column="Movement_ID",
        filters=(
            (
                "Movement_Type",
                "equals",
                "Transfer",
            ),
        ),
        historical_table="monthly_snapshots",
        historical_column="Employees_Transferred_Out",
        aliases=(
            "transfers out",
            "employees transferred out",
            "outgoing transfers",
            "transfer outflow",
        ),
    ),
    "monthly_net_workforce_change": MetricDefinition(
        name="monthly_net_workforce_change",
        display_name="Monthly Net Workforce Change",
        category="movement",
        unit="employees",
        description=(
            "Net monthly workforce change after joiners, leavers "
            "and transfers."
        ),
        source_tables=("monthly_snapshots",),
        operation="derived",
        formula=(
            "employees_joining_during_month + "
            "employees_transferred_in - "
            "employees_leaving_during_month - "
            "employees_transferred_out"
        ),
        historical_table="monthly_snapshots",
        aliases=(
            "net workforce change",
            "monthly headcount change",
            "net employee movement",
            "net headcount movement",
        ),
    ),

    # --------------------------------------------------------
    # DAILY AVAILABILITY
    # --------------------------------------------------------

    "employees_available_for_work": MetricDefinition(
        name="employees_available_for_work",
        display_name="Employees Available for Work",
        category="availability",
        unit="employees",
        description=(
            "Employees available to work on the selected activity date."
        ),
        source_tables=("daily_activity",),
        operation="sum",
        source_column="Employees_Available_for_Work",
        aliases=(
            "available employees",
            "employees working today",
            "workforce available",
        ),
    ),

    "employees_on_approved_leave": MetricDefinition(
        name="employees_on_approved_leave",
        display_name="Employees on Approved Leave",
        category="availability",
        unit="employees",
        description=(
            "Employees recorded as being on approved leave."
        ),
        source_tables=("daily_activity",),
        operation="sum",
        source_column="Employees_on_Approved_Leave",
        aliases=(
            "employees on leave",
            "approved leave count",
            "staff on leave",
        ),
    ),

    "employees_absent": MetricDefinition(
        name="employees_absent",
        display_name="Employees Absent",
        category="availability",
        unit="employees",
        description="Employees recorded as absent.",
        source_tables=("daily_activity",),
        operation="sum",
        source_column="Employees_Absent",
        aliases=(
            "absent employees",
            "employee absence",
            "staff absent",
            "absence count",
        ),
    ),

    "total_overtime_hours": MetricDefinition(
        name="total_overtime_hours",
        display_name="Total Overtime Hours",
        category="availability",
        unit="hours",
        description=(
            "Total overtime hours recorded for the selected scope."
        ),
        source_tables=("daily_activity",),
        operation="sum",
        source_column="Total_Overtime_Hours",
        aliases=(
            "overtime",
            "overtime hours",
            "workforce overtime",
        ),
    ),

    "workforce_availability_percentage": MetricDefinition(
        name="workforce_availability_percentage",
        display_name="Workforce Availability",
        category="availability",
        unit="percentage",
        description=(
            "Employees available for work as a percentage of actual "
            "employees."
        ),
        source_tables=("daily_activity",),
        operation="derived",
        formula=(
            "employees_available_for_work / "
            "actual_employee_count * 100"
        ),
        historical_table="daily_activity",
        historical_column="Workforce_Availability_Percentage",
        aliases=(
            "workforce availability",
            "availability percentage",
            "employee availability rate",
            "staff availability",
        ),
    ),
    "daily_open_position_count": MetricDefinition(
        name="daily_open_position_count",
        display_name="Daily Open Position Count",
        category="availability",
        unit="positions",
        description=(
            "Open positions recorded in the daily workforce "
            "activity snapshot."
        ),
        source_tables=("daily_activity",),
        operation="sum",
        source_column="Open_Position_Count",
        historical_table="daily_activity",
        historical_column="Open_Position_Count",
        aliases=(
            "open positions today",
            "daily open positions",
            "today's open positions",
            "current daily open positions",
        ),
    ),

    "daily_critical_open_position_count": MetricDefinition(
        name="daily_critical_open_position_count",
        display_name="Daily Critical Open Position Count",
        category="availability",
        unit="positions",
        description=(
            "Critical open positions recorded in the daily "
            "workforce activity snapshot."
        ),
        source_tables=("daily_activity",),
        operation="sum",
        source_column="Critical_Open_Position_Count",
        historical_table="daily_activity",
        historical_column="Critical_Open_Position_Count",
        aliases=(
            "critical open positions today",
            "daily critical open positions",
            "today's critical vacancies",
        ),
    ),
    # --------------------------------------------------------
    # VACANCY DETAILS
    # --------------------------------------------------------

    "vacancy_age_in_days": MetricDefinition(
        name="vacancy_age_in_days",
        display_name="Vacancy Age",
        category="vacancies",
        unit="days",
        description=(
            "Number of calendar days a position has remained vacant."
        ),
        source_tables=("vacancy_history",),
        operation="contextual",
        source_column="Vacancy_Age_in_Days",
        aliases=(
            "vacancy age",
            "days vacant",
            "how long vacant",
            "days position has been open",
        ),
    ),
    "average_vacancy_age_in_days": MetricDefinition(
        name="average_vacancy_age_in_days",
        display_name="Average Vacancy Age",
        category="vacancies",
        unit="days",
        description=(
            "Average number of days that the selected currently "
            "open positions have remained vacant."
        ),
        source_tables=("vacancy_history",),
        operation="average",
        source_column="Vacancy_Age_in_Days",
        aliases=(
            "average vacancy age",
            "average days vacant",
            "mean vacancy age",
            "average open position age",
        ),
    ),

    "overdue_vacancy_count": MetricDefinition(
        name="overdue_vacancy_count",
        display_name="Overdue Vacancy Count",
        category="vacancies",
        unit="positions",
        description=(
            "Currently open vacancies whose target fill date is "
            "earlier than the workforce reporting date."
        ),
        source_tables=("vacancy_history",),
        operation="count_distinct",
        source_column="Position_ID",
        aliases=(
            "overdue vacancies",
            "vacancies past target date",
            "late vacancies",
            "positions overdue for hiring",
        ),
    ),

    "average_time_to_fill_in_days": MetricDefinition(
        name="average_time_to_fill_in_days",
        display_name="Average Time to Fill",
        category="vacancies",
        unit="days",
        description=(
            "Average actual number of days taken to fill completed "
            "vacancies."
        ),
        source_tables=("vacancy_history",),
        operation="average",
        source_column="Actual_Time_to_Fill_in_Days",
        aliases=(
            "average time to fill",
            "average hiring time",
            "mean time to fill",
            "average vacancy fill time",
        ),
    ),
    "long_open_vacancy_count": MetricDefinition(
        name="long_open_vacancy_count",
        display_name="Vacancies Open More Than 90 Days",
        category="vacancies",
        unit="positions",
        description=(
            "Currently open vacancies older than 90 calendar days."
        ),
        source_tables=("vacancy_history",),
        operation="count_distinct",
        source_column="Position_ID",
        filters=(
            (
                "Vacancy_Status",
                "equals",
                "Currently Open",
            ),
            (
                "Vacancy_Age_in_Days",
                "greater_than",
                90,
            ),
        ),
        aliases=(
            "long open vacancies",
            "vacancies older than 90 days",
            "aged vacancies",
            "old vacancies",
        ),
    ),

    "critical_open_position_count": MetricDefinition(
        name="critical_open_position_count",
        display_name="Critical or High-Priority Open Positions",
        category="vacancies",
        unit="positions",
        description=(
            "Open positions with High or Critical position "
            "criticality."
        ),
        source_tables=(
            "positions",
            "vacancy_history",
        ),
        operation="count_distinct",
        source_column="Position_ID",
        filters=(
            (
                "Position_Criticality",
                "in",
                ("High", "Critical"),
            ),
            (
                "Position_Status",
                "in",
                ("Vacant", "Frozen"),
            ),
        ),
        aliases=(
            "critical vacancies",
            "high priority vacancies",
            "critical open positions",
            "high criticality positions",
        ),
    ),

    # --------------------------------------------------------
    # EXCEPTIONS AND DEMAND
    # --------------------------------------------------------

    "open_exception_count": MetricDefinition(
        name="open_exception_count",
        display_name="Open Headcount Exception Count",
        category="exceptions",
        unit="exceptions",
        description=(
            "Count of currently open Headcount Management exceptions."
        ),
        source_tables=("exceptions",),
        operation="count_distinct",
        source_column="Exception_ID",
        filters=(
            (
                "Exception_Status",
                "equals",
                "Open",
            ),
        ),
        aliases=(
            "open exceptions",
            "headcount exceptions",
            "workforce exceptions",
            "staffing alerts",
            "exceptions",
        ),
    ),
    "critical_exception_count": MetricDefinition(
        name="critical_exception_count",
        display_name="Critical Headcount Exception Count",
        category="exceptions",
        unit="exceptions",
        description=(
            "Count of open Headcount exceptions classified "
            "as Critical."
        ),
        source_tables=("exceptions",),
        operation="count_distinct",
        source_column="Exception_ID",
        filters=(
            (
                "Exception_Status",
                "equals",
                "Open",
            ),
            (
                "Severity",
                "equals",
                "Critical",
            ),
        ),
        aliases=(
            "critical exceptions",
            "critical headcount exceptions",
            "critical workforce exceptions",
            "critical staffing alerts",
        ),
    ),

    "warning_exception_count": MetricDefinition(
        name="warning_exception_count",
        display_name="Warning Headcount Exception Count",
        category="exceptions",
        unit="exceptions",
        description=(
            "Count of open Headcount exceptions classified "
            "as Warning."
        ),
        source_tables=("exceptions",),
        operation="count_distinct",
        source_column="Exception_ID",
        filters=(
            (
                "Exception_Status",
                "equals",
                "Open",
            ),
            (
                "Severity",
                "equals",
                "Warning",
            ),
        ),
        aliases=(
            "warning exceptions",
            "warning headcount exceptions",
            "warning workforce exceptions",
            "warning staffing alerts",
        ),
    ),

    "active_rule_count": MetricDefinition(
        name="active_rule_count",
        display_name="Active Headcount Rule Count",
        category="governance",
        unit="rules",
        description=(
            "Count of Headcount Management rules effective "
            "on the reporting date."
        ),
        source_tables=("rules",),
        operation="count_distinct",
        source_column="Rule_ID",
        aliases=(
            "headcount rules",
            "workforce rules",
            "active rules",
            "staffing rules",
            "rule count",
        ),
    ),
    "demand_to_approved_headcount_gap": MetricDefinition(
        name="demand_to_approved_headcount_gap",
        display_name="Demand-to-Approved Headcount Gap",
        category="demand",
        unit="positions",
        description=(
            "Difference between demand-driven staffing need and "
            "approved positions."
        ),
        source_tables=("demand_drivers",),
        operation="sum",
        source_column="Demand_to_Approved_Headcount_Gap",
        historical_table="demand_drivers",
        historical_column="Demand_to_Approved_Headcount_Gap",
        aliases=(
            "demand headcount gap",
            "staffing demand gap",
            "required versus approved headcount",
            "demand versus approved",
        ),
    ),

    # --------------------------------------------------------
    # EXTERNAL ATTRITION METRIC
    # --------------------------------------------------------

    "expected_employee_exits": MetricDefinition(
        name="expected_employee_exits",
        display_name="Expected Employee Exits",
        category="attrition",
        unit="employees",
        description=(
            "Probability-weighted expected exits produced by the "
            "existing Attrition prediction service."
        ),
        source_tables=(),
        operation="external",
        formula=(
            "sum of employee attrition probabilities"
        ),
        aliases=(
            "expected exits",
            "predicted employee exits",
            "expected attrition count",
        ),
        external_dependency=True,
    ),
}


# ============================================================
# DIMENSION REGISTRY
# ============================================================

DIMENSIONS: Final[dict[str, DimensionDefinition]] = {
    "employee": DimensionDefinition(
        name="employee",
        display_name="Employee",
        description="Individual employee identity.",
        source_columns=(
            ("employees", "Employee_ID"),
            ("assignments", "Employee_ID"),
            ("movements", "Employee_ID"),
        ),
        aliases=(
            "employee id",
            "employee name",
            "staff member",
            "person",
        ),
    ),

    "position": DimensionDefinition(
        name="position",
        display_name="Position",
        description="Approved or occupied organizational position.",
        source_columns=(
            ("positions", "Position_ID"),
            ("assignments", "Position_ID"),
            ("vacancy_history", "Position_ID"),
            ("position_budgets", "Position_ID"),
        ),
        aliases=(
            "position id",
            "position title",
            "role",
            "job position",
        ),
    ),
    "career_level": DimensionDefinition(
        name="career_level",
        display_name="Career Level",
        description="Employee career-level classification.",
        source_columns=(
            ("employees", "Career_Level"),
        ),
        aliases=(
            "career level",
            "career band",
        ),
    ),

    "shift_type": DimensionDefinition(
        name="shift_type",
        display_name="Shift Type",
        description="Employee working shift.",
        source_columns=(
            ("employees", "Shift_Type"),
        ),
        aliases=(
            "shift",
            "shift type",
            "work shift",
        ),
    ),

    "employee_category": DimensionDefinition(
        name="employee_category",
        display_name="Employee Category",
        description=(
            "Regular, contract, internship, or another "
            "employee category."
        ),
        source_columns=(
            ("employees", "Employee_Category"),
        ),
        aliases=(
            "employee category",
            "worker category",
        ),
    ),

    "headcount_inclusion_category": DimensionDefinition(
        name="headcount_inclusion_category",
        display_name="Headcount Inclusion Category",
        description=(
            "Category under which an employee is included "
            "in workforce Headcount."
        ),
        source_columns=(
            (
                "employees",
                "Headcount_Inclusion_Category",
            ),
        ),
        aliases=(
            "headcount inclusion category",
            "headcount category",
        ),
    ),

    "included_in_approved_headcount": DimensionDefinition(
        name="included_in_approved_headcount",
        display_name="Included in Approved Headcount",
        description=(
            "Whether an employee is included in approved "
            "Headcount."
        ),
        source_columns=(
            (
                "employees",
                "Included_in_Approved_Headcount",
            ),
        ),
        aliases=(
            "approved headcount inclusion",
            "included in approved headcount",
        ),
    ),
    "department": DimensionDefinition(
        name="department",
        display_name="Department",
        description="Department-level organizational grouping.",
        source_columns=(
            ("employees", "Department"),
            ("assignments", "Department_Name"),
            ("positions", "Department"),
            ("current_summary", "Department_Name"),
            ("vacancy_history", "Department_Name"),
            ("monthly_snapshots", "Department_Name"),
            ("department_budgets", "Department_Name"),
            ("daily_activity", "Department_Name"),
            ("exceptions", "Department_Name"),
            ("demand_drivers", "Department_Name"),
        ),
        aliases=(
            "department name",
            "dept",
            "division",
        ),
    ),

    "business_unit": DimensionDefinition(
        name="business_unit",
        display_name="Business Unit",
        description="Business-unit organizational grouping.",
        source_columns=(
            ("employees", "Business_Unit"),
            ("assignments", "Business_Unit"),
            ("positions", "Business_Unit"),
            ("current_summary", "Business_Unit"),
            ("monthly_snapshots", "Business_Unit"),
        ),
        aliases=(
            "business unit",
            "business division",
            "bu",
        ),
    ),

    "organizational_unit": DimensionDefinition(
        name="organizational_unit",
        display_name="Organizational Unit",
        description="Team or other organizational hierarchy unit.",
        source_columns=(
            ("employees", "Organizational_Unit_ID"),
            ("assignments", "Organizational_Unit_ID"),
            ("positions", "Organizational_Unit_ID"),
            ("vacancy_history", "Organizational_Unit_ID"),
        ),
        aliases=(
            "team",
            "organizational unit",
            "org unit",
        ),
    ),

    "work_location": DimensionDefinition(
        name="work_location",
        display_name="Work Location",
        description="Employee or position work location.",
        source_columns=(
            ("employees", "Work_Location_ID"),
            ("assignments", "Work_Location_ID"),
            ("positions", "Work_Location_ID"),
        ),
        aliases=(
            "location",
            "office",
            "site",
            "workplace",
        ),
    ),

    "cost_center": DimensionDefinition(
        name="cost_center",
        display_name="Cost Center",
        description="Financial cost-center grouping.",
        source_columns=(
            ("employees", "Cost_Center_ID"),
            ("assignments", "Cost_Center_ID"),
            ("positions", "Cost_Center_ID"),
            ("department_budgets", "Cost_Center_ID"),
        ),
        aliases=(
            "cost centre",
            "finance center",
            "finance centre",
        ),
    ),

    "job_level": DimensionDefinition(
    name="job_level",
    display_name="Job Level",
    description="Employee or position seniority level.",
    source_columns=(
        ("employees", "Job_Level"),
        ("positions", "Job_Level"),
    ),
    aliases=(
        "seniority",
        "grade",
        "employee level",
        "job grade",
    ),
),

    "employment_type": DimensionDefinition(
        name="employment_type",
        display_name="Employment Type",
        description="Permanent, contract, internship or other type.",
        source_columns=(
            ("employees", "Employment_Type"),
            ("assignments", "Employment_Type"),
            ("positions", "Employment_Type"),
        ),
        aliases=(
            "contract type",
            "employee type",
            "worker type",
        ),
    ),

    "employee_status": DimensionDefinition(
        name="employee_status",
        display_name="Employee Status",
        description="Current status of an employee.",
        source_columns=(
            ("employees", "Employee_Status"),
        ),
        aliases=(
            "staff status",
            "employment status",
        ),
    ),

    "work_mode": DimensionDefinition(
        name="work_mode",
        display_name="Work Mode",
        description="On-site, hybrid or remote work arrangement.",
        source_columns=(
            ("employees", "Work_Mode"),
            ("positions", "Work_Mode_Requirement"),
        ),
        aliases=(
            "working mode",
            "remote status",
            "hybrid status",
        ),
    ),

    "position_status": DimensionDefinition(
        name="position_status",
        display_name="Position Status",
        description="Filled, Vacant or Frozen position status.",
        source_columns=(
            ("positions", "Position_Status"),
            ("position_budgets", "Position_Status"),
        ),
        aliases=(
            "job status",
            "role status",
        ),
    ),

    "position_criticality": DimensionDefinition(
        name="position_criticality",
        display_name="Position Criticality",
        description="Low, Medium, High or Critical position priority.",
        source_columns=(
            ("positions", "Position_Criticality"),
            ("vacancy_history", "Position_Criticality"),
        ),
        aliases=(
            "criticality",
            "position priority",
            "vacancy priority",
        ),
    ),

    "vacancy_status": DimensionDefinition(
        name="vacancy_status",
        display_name="Vacancy Status",
        description="Current or historical vacancy status.",
        source_columns=(
            ("vacancy_history", "Vacancy_Status"),
        ),
        aliases=(
            "open vacancy status",
            "vacancy state",
        ),
    ),

    "recruitment_stage": DimensionDefinition(
        name="recruitment_stage",
        display_name="Recruitment Stage",
        description="Current hiring stage for a vacancy.",
        source_columns=(
            ("vacancy_history", "Recruitment_Stage"),
        ),
        aliases=(
            "hiring stage",
            "recruitment status",
            "hiring status",
        ),
    ),

    "movement_type": DimensionDefinition(
        name="movement_type",
        display_name="Movement Type",
        description="Join, Leave, Promotion or Transfer movement.",
        source_columns=(
            ("movements", "Movement_Type"),
        ),
        aliases=(
            "employee movement",
            "workforce movement",
        ),
    ),

    "exception_type": DimensionDefinition(
        name="exception_type",
        display_name="Exception Type",
        description="Headcount exception category.",
        source_columns=(
            ("exceptions", "Exception_Type"),
        ),
        aliases=(
            "alert type",
            "issue type",
        ),
    ),

    "severity": DimensionDefinition(
        name="severity",
        display_name="Severity",
        description="Warning or Critical exception severity.",
        source_columns=(
            ("exceptions", "Severity"),
        ),
        aliases=(
            "priority",
            "alert severity",
            "issue severity",
        ),
    ),

    "month": DimensionDefinition(
        name="month",
        display_name="Month",
        description="Monthly reporting period.",
        source_columns=(
            ("monthly_snapshots", "Snapshot_Month"),
            ("department_budgets", "Budget_Month"),
            ("demand_drivers", "Snapshot_Month"),
        ),
        aliases=(
            "monthly",
            "snapshot month",
            "budget month",
        ),
    ),

    "activity_date": DimensionDefinition(
        name="activity_date",
        display_name="Activity Date",
        description="Daily workforce reporting date.",
        source_columns=(
            ("daily_activity", "Activity_Date"),
        ),
        aliases=(
            "date",
            "day",
            "today",
            "daily",
        ),
    ),
}


# ============================================================
# ALIAS RESOLUTION
# ============================================================

def normalize_registry_term(value: str) -> str:
    """Normalize metric or dimension names for alias matching."""

    normalized = re.sub(
        r"[^a-z0-9]+",
        "_",
        str(value).strip().lower(),
    )

    return normalized.strip("_")


def _build_alias_index(
    definitions: Mapping[
        str,
        MetricDefinition | DimensionDefinition,
    ],
) -> dict[str, str]:
    """Build alias-to-canonical-name lookup safely."""

    index: dict[str, str] = {}

    for canonical_name, definition in definitions.items():
        candidate_terms = (
            canonical_name,
            definition.display_name,
            *definition.aliases,
        )

        for term in candidate_terms:
            normalized = normalize_registry_term(term)

            existing = index.get(normalized)

            if (
                existing is not None
                and existing != canonical_name
            ):
                raise ValueError(
                    f"Registry alias collision for {term!r}: "
                    f"{existing!r} and {canonical_name!r}."
                )

            index[normalized] = canonical_name

    return index

METRIC_ALIAS_INDEX: Final[dict[str, str]] = (
    _build_alias_index(METRICS)
)

DIMENSION_ALIAS_INDEX: Final[dict[str, str]] = (
    _build_alias_index(DIMENSIONS)
)


# ============================================================
# PUBLIC REGISTRY FUNCTIONS
# ============================================================

def resolve_metric_name(value: str) -> str | None:
    """Resolve a metric name or alias to its canonical name."""

    return METRIC_ALIAS_INDEX.get(
        normalize_registry_term(value)
    )


def resolve_dimension_name(value: str) -> str | None:
    """Resolve a dimension name or alias to its canonical name."""

    return DIMENSION_ALIAS_INDEX.get(
        normalize_registry_term(value)
    )


def get_metric_definition(
    metric_name: str,
) -> MetricDefinition | None:
    """Return a metric definition using a name or alias."""

    resolved_name = resolve_metric_name(metric_name)

    if resolved_name is None:
        return None

    return METRICS[resolved_name]


def get_dimension_definition(
    dimension_name: str,
) -> DimensionDefinition | None:
    """Return a dimension definition using a name or alias."""

    resolved_name = resolve_dimension_name(
        dimension_name
    )

    if resolved_name is None:
        return None

    return DIMENSIONS[resolved_name]


def list_metric_names() -> tuple[str, ...]:
    """Return all canonical metric names."""

    return tuple(METRICS.keys())


def list_dimension_names() -> tuple[str, ...]:
    """Return all canonical dimension names."""

    return tuple(DIMENSIONS.keys())