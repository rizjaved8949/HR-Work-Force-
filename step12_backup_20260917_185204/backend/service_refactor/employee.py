"""Graph-native employee retrieval with the legacy tool/API response contract.

Step 9 intentionally preserves the existing `get_employee_record` payload so the
already-built UI and LangGraph agent do not need a coordinated rewrite.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Callable, Optional, cast

from rapidfuzz import fuzz

from employee_record_tool import EmployeeRecordSearchInput, tool
from mapping.registry import DEFAULT_MAPPING_REGISTRY, MappingRegistry
from semantic.models import EmployeeContext, SemanticRecord
from semantic.service import SemanticHRService


class GraphEmployeeRecordService:
    """Build the old employee-record shape from canonical semantic graph facts."""

    # These current CSV columns historically carry Yes/No strings while the
    # ontology correctly stores booleans. Convert only at the compatibility
    # boundary so the existing UI/tool payload stays stable.
    _LEGACY_YES_NO_COLUMNS = {
        "Included_in_Approved_Headcount",
        "Approved_Position",
        "Budgeted_Position",
        "Mandatory_Flag",
        "Is_Primary_Skill",
        "Pay_Concern_Raised_Last_6M",
        "Manager_Changed_Last_6M",
    }

    _SOURCE_FILES = {
        "profile": "Employee_Profile.csv",
        "attendance": "Employee_Attendance.csv",
        "performance": "Employee_Performance.csv",
        "experience": "Employee_Experience.csv",
        "attrition_features": "Final_Attrition_Dataset_200_Employees.csv",
        "position_requirements": "Position_Requirements.csv",
    }

    def __init__(
        self,
        semantic_service: SemanticHRService,
        *,
        tenant_id: str | Callable[[], str],
        mapping_registry: MappingRegistry = DEFAULT_MAPPING_REGISTRY,
    ) -> None:
        self.semantic_service = semantic_service
        self._tenant_id_source = tenant_id
        self.mapping_registry = mapping_registry

    def _tenant_id(self) -> str:
        value = self._tenant_id_source() if callable(self._tenant_id_source) else self._tenant_id_source
        tenant_id = str(value).strip()
        if not tenant_id:
            raise RuntimeError("Resolved tenant_id must not be empty")
        return tenant_id

    @staticmethod
    def _normalize_text(value: Any) -> str:
        if value is None:
            return ""
        text = unicodedata.normalize("NFKD", str(value))
        text = "".join(ch for ch in text if not unicodedata.combining(ch))
        text = re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()
        return " ".join(text.split())

    @classmethod
    def _legacy_value(cls, source_column: str, value: Any) -> Any:
        if source_column in cls._LEGACY_YES_NO_COLUMNS and isinstance(value, bool):
            return "Yes" if value else "No"
        return value

    @staticmethod
    def _record_value(record: SemanticRecord | None, property_name: str) -> Any:
        if record is None:
            return None
        return record.properties.get(property_name)

    @staticmethod
    def _first(records: list[SemanticRecord]) -> SemanticRecord | None:
        return records[0] if records else None

    def _entity_records(self, context: EmployeeContext) -> dict[str, SemanticRecord | None]:
        return {
            "Employee": context.employee,
            "Employment": context.employment,
            "Assignment": context.current_assignment,
            "Department": context.department,
            "BusinessUnit": context.business_unit,
            "OrganizationalUnit": context.organizational_unit,
            "WorkLocation": context.work_location,
            "CostCenter": context.cost_center,
            "Position": context.position,
            "PositionBudget": context.position_budget,
            "VacancyRecord": context.vacancy,
            "CompensationRecord": context.compensation,
            "PerformanceRecord": context.performance,
            "PerformanceSummary": context.performance_summary,
            "AttendanceRecord": context.attendance,
            "EngagementRecord": context.engagement,
            "ExperienceProfile": context.experience,
            "SuccessionReadiness": context.succession_readiness,
            "PositionRequirement": self._first(context.position_requirements),
        }

    def _mapped_record(
        self,
        source_file: str,
        context: EmployeeContext,
        *,
        overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        entity_records = self._entity_records(context)
        output: dict[str, Any] = {}
        dataset = self.mapping_registry.dataset(source_file)
        for item in dataset.get("columns", []):
            disposition = item.get("disposition")
            ontology_path = item.get("ontology_path")
            if disposition not in {"direct_property", "context_property"} or not ontology_path:
                continue
            entity_name, property_name = str(ontology_path).split(".", 1)
            record = entity_records.get(entity_name)
            value = self._record_value(record, property_name)
            if value is not None and value != "":
                source_column = str(item["source_column"])
                output[source_column] = self._legacy_value(source_column, value)

        # Relationship references that are intentionally not scalar ontology
        # properties are reconstructed only when an unambiguous graph relation exists.
        manager = context.manager
        if source_file == "Employee_Profile.csv" and manager is not None:
            manager_id = manager.properties.get("employeeId")
            if manager_id:
                output["Manager_Employee_ID"] = manager_id

        if source_file in {"Position_Master.csv", "Position_Requirements.csv"}:
            output.setdefault("Current_Employee_ID", context.employee.properties.get("employeeId"))
            output.setdefault("Current_Employee_Name", context.employee.properties.get("name"))
            if context.reporting_position is not None:
                output.setdefault(
                    "Reporting_Position_ID",
                    context.reporting_position.properties.get("positionId"),
                )
                output.setdefault(
                    "Reporting_Title",
                    context.reporting_position.properties.get("title")
                    or context.reporting_position.properties.get("designation"),
                )

        if overrides:
            output.update({k: v for k, v in overrides.items() if v is not None})
        return output

    def _skill_records(self, context: EmployeeContext) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        employee_id = context.employee.properties.get("employeeId")
        employee_name = context.employee.properties.get("name")
        department_name = context.department.properties.get("name") if context.department else None
        department_id = context.department.properties.get("departmentId") if context.department else None
        position_id = context.position.properties.get("positionId") if context.position else None
        business_unit = context.business_unit.properties.get("name") if context.business_unit else None
        organizational_unit_id = (
            context.organizational_unit.properties.get("organizationalUnitId")
            if context.organizational_unit else None
        )
        work_location_id = (
            context.work_location.properties.get("workLocationId")
            if context.work_location else None
        )

        for item in context.skills:
            assessment = item.assessment
            skill = item.skill
            row: dict[str, Any] = {
                "Employee_ID": employee_id,
                "Employee_Name": employee_name,
                "Department": department_name,
                "Department_ID": department_id,
                "Position_ID": position_id,
                "Business_Unit": business_unit,
                "Organizational_Unit_ID": organizational_unit_id,
                "Work_Location_ID": work_location_id,
            }
            if skill is not None:
                row.update({
                    "Skill_ID": skill.properties.get("skillId"),
                    "Skill_Name": skill.properties.get("name"),
                    "Skill_Category": skill.properties.get("category"),
                    "Skill_Type": skill.properties.get("skillType"),
                })
            mapping = {
                "Skill_Status": "skillStatus",
                "Proficiency_Level": "proficiencyLevel",
                "Proficiency_Label": "proficiencyLabel",
                "Skill_Score": "skillScore",
                "Years_Using_Skill": "yearsUsingSkill",
                "Last_Assessed_Months_Ago": "lastAssessedMonthsAgo",
                "Certification_Status": "certificationStatus",
                "Is_Primary_Skill": "isPrimarySkill",
                "Data_As_Of_Date": "dataAsOfDate",
            }
            for legacy_name, prop in mapping.items():
                value = assessment.properties.get(prop)
                if value is not None:
                    row[legacy_name] = self._legacy_value(legacy_name, value)
            rows.append({k: v for k, v in row.items() if v is not None})
        return rows

    def _skill_catalog(self, context: EmployeeContext) -> list[dict[str, Any]]:
        seen: set[str] = set()
        rows: list[dict[str, Any]] = []
        for item in context.skills:
            skill = item.skill
            if skill is None:
                continue
            skill_id = str(skill.properties.get("skillId") or skill.reference_id)
            if skill_id in seen:
                continue
            seen.add(skill_id)
            rows.append({
                "Skill_ID": skill.properties.get("skillId"),
                "Skill_Name": skill.properties.get("name"),
                "Skill_Category": skill.properties.get("category"),
                "Skill_Type": skill.properties.get("skillType"),
            })
        return [{k: v for k, v in row.items() if v is not None} for row in rows]

    def _position_skill_requirement_records(self, context: EmployeeContext) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        base = {
            "Position_ID": context.position.properties.get("positionId") if context.position else None,
            "Position_Title": context.position.properties.get("title") if context.position else None,
            "Designation": context.position.properties.get("designation") if context.position else None,
            "Department": context.department.properties.get("name") if context.department else None,
            "Department_ID": context.department.properties.get("departmentId") if context.department else None,
            "Business_Unit": context.business_unit.properties.get("name") if context.business_unit else None,
            "Organizational_Unit_ID": (
                context.organizational_unit.properties.get("organizationalUnitId")
                if context.organizational_unit else None
            ),
        }
        prop_map = {
            "Requirement_Type": "requirementType",
            "Mandatory_Flag": "mandatory",
            "Minimum_Proficiency_Level": "minimumProficiencyLevel",
            "Minimum_Skill_Score": "minimumSkillScore",
            "Skill_Weight_pct": "skillWeightPercentage",
            "Data_As_Of_Date": "dataAsOfDate",
        }
        for requirement in context.position_skill_requirements:
            row = dict(base)
            skill = self.semantic_service.get_position_skill_requirement_skill(
                tenant_id=self._tenant_id(),
                requirement_reference_id=requirement.reference_id,
            )
            if skill is not None:
                row.update({
                    "Skill_ID": skill.properties.get("skillId"),
                    "Skill_Name": skill.properties.get("name"),
                    "Skill_Category": skill.properties.get("category"),
                })
            for legacy, prop in prop_map.items():
                value = requirement.properties.get(prop)
                if value is not None:
                    row[legacy] = self._legacy_value(legacy, value)
            rows.append({k: v for k, v in row.items() if v is not None})
        return rows

    @staticmethod
    def _skill_summaries(position_skill_rows: list[dict[str, Any]]) -> tuple[str | None, str | None]:
        required: list[str] = []
        preferred: list[str] = []
        for row in position_skill_rows:
            name = str(row.get("Skill_Name") or "").strip()
            kind = str(row.get("Requirement_Type") or "").strip().casefold()
            if not name:
                continue
            if kind == "required" and name not in required:
                required.append(name)
            elif kind == "preferred" and name not in preferred:
                preferred.append(name)
        return (", ".join(required) or None, ", ".join(preferred) or None)

    def get_by_employee_id(self, employee_id: str, *, match_method: str = "employee_id") -> dict[str, Any]:
        context = self.semantic_service.get_employee_context(
            tenant_id=self._tenant_id(),
            employee_id=str(employee_id).strip(),
        )
        if context is None:
            return {
                "status": "not_found",
                "message": f"No employee was found with Employee ID '{employee_id}'.",
                "searched_employee_id": employee_id,
            }

        employee = context.employee.properties
        position = context.position.properties if context.position else {}
        department = context.department.properties if context.department else {}
        employment = context.employment.properties if context.employment else {}
        location = context.work_location.properties if context.work_location else {}

        profile = self._mapped_record("Employee_Profile.csv", context)
        attrition = self._mapped_record("Final_Attrition_Dataset_200_Employees.csv", context)
        attendance = self._mapped_record("Employee_Attendance.csv", context)
        performance = self._mapped_record("Employee_Performance.csv", context)
        experience = self._mapped_record("Employee_Experience.csv", context)
        position_skill_requirements = self._position_skill_requirement_records(context)
        required_summary, preferred_summary = self._skill_summaries(position_skill_requirements)
        position_requirements = self._mapped_record(
            "Position_Requirements.csv",
            context,
            overrides={
                "Required_Skills_Summary": required_summary,
                "Preferred_Skills_Summary": preferred_summary,
            },
        )

        return {
            "status": "found",
            "match_method": match_method,
            "employee": {
                "employee_id": employee.get("employeeId"),
                "employee_name": employee.get("name"),
                "name_aliases": [],
                "department": department.get("name"),
                "designation": position.get("designation") or position.get("title"),
                "office": location.get("name") or location.get("city"),
                "job_level": employment.get("jobLevel") or position.get("jobLevel"),
                "position_ids": [position.get("positionId")] if position.get("positionId") else [],
            },
            "records": {
                "profile": profile,
                "attendance": attendance,
                "performance": performance,
                "experience": experience,
                "skills": self._skill_records(context),
                "attrition_features": attrition,
                "position": self._mapped_record("Position_Master.csv", context),
                "position_requirements": position_requirements,
                "position_skill_requirements": position_skill_requirements,
                "skill_catalog": self._skill_catalog(context),
            },
            "data_quality": {
                "duplicates_removed": 0,
                "conflicts": [],
                "missing_relations": [],
                "csv_tables_scanned": 0,
                "source_files_returned": [],
                "runtime_source": "knowledge_graph",
                "ontology_version": self.semantic_service.schema.ontology_version,
            },
        }

    def _candidate_view(self, employee_id: str) -> dict[str, Any] | None:
        context = self.semantic_service.get_employee_context(
            tenant_id=self._tenant_id(), employee_id=employee_id
        )
        if context is None:
            return None
        employee = context.employee.properties
        position = context.position.properties if context.position else {}
        department = context.department.properties if context.department else {}
        location = context.work_location.properties if context.work_location else {}
        return {
            "employee_id": employee.get("employeeId"),
            "employee_name": employee.get("name"),
            "department": department.get("name"),
            "designation": position.get("designation") or position.get("title"),
            "position_id": position.get("positionId"),
            "office": location.get("name") or location.get("city"),
        }

    def _matches_filters(
        self,
        candidate: dict[str, Any],
        *,
        department: str | None,
        designation: str | None,
        position_id: str | None,
        office: str | None,
    ) -> bool:
        def contains(actual: Any, requested: str | None) -> bool:
            if not requested:
                return True
            return self._normalize_text(requested) in self._normalize_text(actual)

        if not contains(candidate.get("department"), department):
            return False
        if not contains(candidate.get("designation"), designation):
            return False
        if position_id and str(candidate.get("position_id") or "").casefold() != str(position_id).strip().casefold():
            return False
        if not contains(candidate.get("office"), office):
            return False
        return True

    def search(
        self,
        *,
        employee_id: Optional[str] = None,
        employee_name: Optional[str] = None,
        department: Optional[str] = None,
        designation: Optional[str] = None,
        position_id: Optional[str] = None,
        office: Optional[str] = None,
    ) -> dict[str, Any]:
        if employee_id:
            return self.get_by_employee_id(employee_id)
        if not employee_name:
            return {"status": "invalid_request", "message": "Provide either employee_id or employee_name."}

        query = self._normalize_text(employee_name)
        employees = self.semantic_service.find_entities(
            tenant_id=self._tenant_id(),
            entity_type="Employee",
            filters=None,
            limit=10_000,
        )
        exact: list[str] = []
        partial: list[str] = []
        fuzzy_matches: list[tuple[float, str]] = []
        query_tokens = set(query.split())
        for record in employees:
            employee_key = str(record.properties.get("employeeId") or "").strip()
            name = self._normalize_text(record.properties.get("name"))
            if not employee_key or not name:
                continue
            if query == name:
                exact.append(employee_key)
                continue
            if query_tokens and query_tokens.issubset(set(name.split())):
                partial.append(employee_key)
                continue
            score = fuzz.WRatio(query, name)
            if score >= 85:
                fuzzy_matches.append((float(score), employee_key))

        match_method = "exact_name"
        ids = exact
        if not ids:
            match_method = "partial_name"
            ids = partial
        if not ids:
            match_method = "fuzzy_name"
            fuzzy_matches.sort(reverse=True)
            ids = [employee_id for _, employee_id in fuzzy_matches[:10]]

        candidates: list[dict[str, Any]] = []
        for candidate_id in ids:
            view = self._candidate_view(candidate_id)
            if view and self._matches_filters(
                view,
                department=department,
                designation=designation,
                position_id=position_id,
                office=office,
            ):
                candidates.append(view)

        if not candidates:
            return {
                "status": "not_found",
                "message": f"No employee matched the name '{employee_name}' and supplied filters.",
                "filters": {
                    "department": department,
                    "designation": designation,
                    "position_id": position_id,
                    "office": office,
                },
            }

        if len(candidates) > 1 or match_method == "fuzzy_name":
            return {
                "status": "needs_clarification",
                "match_method": match_method,
                "message": (
                    "Multiple or approximate employee matches were found. Ask the user to "
                    "select the correct employee, preferably by Employee ID."
                ),
                "candidates": candidates,
                "next_action": "Ask which employee is intended, then call this tool again with employee_id.",
            }

        return self.get_by_employee_id(str(candidates[0]["employee_id"]), match_method=match_method)


def create_graph_employee_record_tool(
    semantic_service: SemanticHRService,
    *,
    tenant_id: str | Callable[[], str],
):
    service = GraphEmployeeRecordService(semantic_service, tenant_id=tenant_id)

    @tool(args_schema=EmployeeRecordSearchInput)
    def get_employee_record(
        employee_id: Optional[str] = None,
        employee_name: Optional[str] = None,
        department: Optional[str] = None,
        designation: Optional[str] = None,
        position_id: Optional[str] = None,
        office: Optional[str] = None,
    ) -> dict[str, Any]:
        """Retrieve one employee from the ontology-backed HR Knowledge Graph.

        The response deliberately preserves the existing employee-record schema so
        the current UI and HR agent can continue without endpoint changes.
        """
        return service.search(
            employee_id=employee_id,
            employee_name=employee_name,
            department=department,
            designation=designation,
            position_id=position_id,
            office=office,
        )

    return cast(Any, get_employee_record)
