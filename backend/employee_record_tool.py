"""Employee record retrieval tool for an HR reasoning LLM.

Purpose
-------
Resolve one employee by Employee ID or name, then collect that employee's
complete, deduplicated record from multiple CSV files. The repository follows
employee, position, and skill relationships but performs no prediction.

The data path may be:
- a folder containing CSV and/or ZIP files,
- one CSV file, or
- one ZIP file containing CSV files.

FastAPI / agent usage
---------------------
    from employee_record_tool import create_employee_record_tool

    employee_tool = create_employee_record_tool(r"D:\\HR_Product\\data")
    result = employee_tool.invoke({"employee_id": "EMP001"})
"""

from __future__ import annotations

import io
import json
import re
import unicodedata
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable, Optional, cast

if TYPE_CHECKING:
    # Import-only for typing. The runtime path below tolerates langchain
    # being absent, so this must not become a hard dependency.
    from langchain_core.tools import BaseTool

import pandas as pd
from pydantic import BaseModel, Field
from rapidfuzz import fuzz

try:
    from langchain.tools import tool
except ImportError:  # Lightweight local fallback; install langchain in the app.
    class _LocalTool:
        def __init__(self, function):
            self.function = function
            self.name = function.__name__
            self.description = function.__doc__ or ""

        def invoke(self, arguments: dict[str, Any]) -> dict[str, Any]:
            return self.function(**arguments)

        def __call__(self, *args, **kwargs):
            return self.function(*args, **kwargs)

    def tool(*decorator_args, **decorator_kwargs):
        def decorate(function):
            return _LocalTool(function)

        if decorator_args and callable(decorator_args[0]):
            return decorate(decorator_args[0])
        return decorate


# ---------------------------------------------------------------------------
# Input schema exposed to the reasoning LLM
# ---------------------------------------------------------------------------


class EmployeeRecordSearchInput(BaseModel):
    employee_id: Optional[str] = Field(
        default=None,
        description=(
            "Unique employee ID from the user's request, such as EMP001, E-102, "
            "or 102. Use this whenever an employee ID is available."
        ),
    )
    employee_name: Optional[str] = Field(
        default=None,
        description=(
            "Employee name from the user's request, such as Sonia Hassan or Ali. "
            "Use this only when employee_id is not available."
        ),
    )
    department: Optional[str] = Field(
        default=None,
        description="Optional department used only to disambiguate a name.",
    )
    designation: Optional[str] = Field(
        default=None,
        description="Optional designation or job title used to disambiguate a name.",
    )
    position_id: Optional[str] = Field(
        default=None,
        description="Optional position ID used to disambiguate a name.",
    )
    office: Optional[str] = Field(
        default=None,
        description="Optional office, branch, or location used to disambiguate a name.",
    )


# ---------------------------------------------------------------------------
# Internal structures
# ---------------------------------------------------------------------------


@dataclass
class LoadedTable:
    key: str
    logical_name: str
    source_file: str
    dataframe: pd.DataFrame
    employee_id_columns: list[str]
    employee_name_columns: list[str]
    position_id_columns: list[str]
    skill_id_columns: list[str]


class EmployeeRecordRepository:
    """Load HR CSV data and retrieve a single consolidated employee record."""

    COLUMN_ALIASES: dict[str, set[str]] = {
        "employee_id": {
            "employeeid",
            "empid",
            "employeecode",
            "currentemployeeid",
            "staffid",
            "personid",
        },
        "employee_name": {
            "employeename",
            "fullname",
            "currentemployeename",
            "staffname",
            "personname",
        },
        "department": {
            "department",
            "departmentname",
            "dept",
            "deptname",
        },
        "designation": {
            "designation",
            "jobtitle",
            "positiontitle",
            "role",
            "rolename",
        },
        "position_id": {
            "positionid",
            "currentpositionid",
            "jobpositionid",
            "postid",
        },
        "skill_id": {
            "skillid",
            "competencyid",
        },
        "office": {
            "office",
            "officename",
            "branch",
            "branchname",
            "location",
            "worklocation",
        },
        "job_level": {
            "joblevel",
            "grade",
            "level",
        },
    }

    # Lower number means more authoritative for identity fields.
    SOURCE_PRIORITY: dict[str, int] = {
        "employee_profile": 0,
        "source_attrition_data": 1,
        "employee_experience": 2,
        "employee_performance": 3,
        "employee_attendance": 4,
        "employee_skills": 5,
        "position_master": 6,
        "position_requirements": 7,
    }

    def __init__(self, data_path: str | Path):
        self.data_path = Path(data_path)
        self.tables: dict[str, LoadedTable] = {}
        self.employee_row_index: dict[str, list[tuple[str, int]]] = defaultdict(list)
        self.position_row_index: dict[str, list[tuple[str, int]]] = defaultdict(list)
        self.skill_row_index: dict[str, list[tuple[str, int]]] = defaultdict(list)
        self.identities: dict[str, dict[str, Any]] = {}
        self.load()

    # ---------------------------- normalization ----------------------------

    @staticmethod
    def _normalize_column(value: Any) -> str:
        return re.sub(r"[^a-z0-9]", "", str(value).casefold())

    @staticmethod
    def _normalize_text(value: Any) -> str:
        if value is None:
            return ""
        text = unicodedata.normalize("NFKD", str(value))
        text = "".join(character for character in text if not unicodedata.combining(character))
        text = re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()
        return " ".join(text.split())

    @staticmethod
    def _normalize_identifier(value: Any) -> str:
        if value is None:
            return ""
        text = str(value).strip()
        if re.fullmatch(r"\d+\.0", text):
            text = text[:-2]
        return re.sub(r"\s+", "", text).casefold()

    @staticmethod
    def _clean_value(value: Any) -> Optional[str]:
        if value is None or pd.isna(value):
            return None
        text = str(value).strip()
        return text or None

    @classmethod
    def _is_alias(cls, column: str, role: str) -> bool:
        return cls._normalize_column(column) in cls.COLUMN_ALIASES[role]

    @classmethod
    def _columns_for_role(cls, columns: Iterable[str], role: str) -> list[str]:
        return [column for column in columns if cls._is_alias(column, role)]

    # ------------------------------ loading --------------------------------

    @staticmethod
    def _read_csv_bytes(raw_bytes: bytes, source: str) -> pd.DataFrame:
        last_error: Optional[Exception] = None
        for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
            try:
                return pd.read_csv(
                    io.BytesIO(raw_bytes),
                    dtype=str,
                    encoding=encoding,
                    keep_default_na=False,
                    low_memory=False,
                )
            except Exception as error:  # pragma: no cover - only used for bad files
                last_error = error
        raise ValueError(f"Unable to read CSV '{source}': {last_error}")

    def _iter_csv_sources(self) -> Iterable[tuple[str, bytes]]:
        if not self.data_path.exists():
            raise FileNotFoundError(f"HR data path does not exist: {self.data_path}")

        if self.data_path.is_file():
            candidate_files = [self.data_path]
            root = self.data_path.parent
        else:
            candidate_files = sorted(
                path
                for path in self.data_path.rglob("*")
                if path.is_file() and path.suffix.casefold() in {".csv", ".zip"}
            )
            root = self.data_path

        for path in candidate_files:
            relative_name = str(path.relative_to(root)).replace("\\", "/")

            if path.suffix.casefold() == ".csv":
                yield relative_name, path.read_bytes()
                continue

            if path.suffix.casefold() == ".zip":
                with zipfile.ZipFile(path) as archive:
                    for member in sorted(archive.namelist()):
                        if member.casefold().endswith(".csv") and not member.endswith("/"):
                            source_name = f"{relative_name}::{member}"
                            yield source_name, archive.read(member)

    def load(self) -> None:
        self.tables.clear()
        self.employee_row_index.clear()
        self.position_row_index.clear()
        self.skill_row_index.clear()
        self.identities.clear()

        source_count = 0
        for source_file, raw_bytes in self._iter_csv_sources():
            dataframe = self._read_csv_bytes(raw_bytes, source_file)
            if dataframe.empty and len(dataframe.columns) == 0:
                continue

            source_count += 1
            logical_name = Path(source_file.split("::")[-1]).stem
            key = f"{logical_name}__{source_count}"

            table = LoadedTable(
                key=key,
                logical_name=logical_name,
                source_file=source_file,
                dataframe=dataframe,
                employee_id_columns=self._columns_for_role(dataframe.columns, "employee_id"),
                employee_name_columns=self._columns_for_role(dataframe.columns, "employee_name"),
                position_id_columns=self._columns_for_role(dataframe.columns, "position_id"),
                skill_id_columns=self._columns_for_role(dataframe.columns, "skill_id"),
            )
            self.tables[key] = table
            self._index_table(table)

        if not self.tables:
            raise FileNotFoundError(f"No readable CSV files were found in: {self.data_path}")
        if not self.employee_row_index:
            raise ValueError(
                "CSV files were loaded, but no supported employee ID column was found. "
                "Add the column name to COLUMN_ALIASES['employee_id']."
            )

        self._build_identity_index()

    def refresh(self) -> None:
        """Reload the source files after data changes."""
        self.load()

    def _index_table(self, table: LoadedTable) -> None:
        dataframe = table.dataframe

        for row_index, row in dataframe.iterrows():
            employee_ids: set[str] = set()
            for column in table.employee_id_columns:
                normalized = self._normalize_identifier(row.get(column))
                if normalized:
                    employee_ids.add(normalized)
            for employee_id in employee_ids:
                self.employee_row_index[employee_id].append((table.key, int(row_index)))

            position_ids: set[str] = set()
            for column in table.position_id_columns:
                normalized = self._normalize_identifier(row.get(column))
                if normalized:
                    position_ids.add(normalized)
            for position_id in position_ids:
                self.position_row_index[position_id].append((table.key, int(row_index)))

            skill_ids: set[str] = set()
            for column in table.skill_id_columns:
                normalized = self._normalize_identifier(row.get(column))
                if normalized:
                    skill_ids.add(normalized)
            for skill_id in skill_ids:
                self.skill_row_index[skill_id].append((table.key, int(row_index)))

    # -------------------------- identity resolution -------------------------

    def _source_rank(self, logical_name: str) -> int:
        return self.SOURCE_PRIORITY.get(self._normalize_text(logical_name).replace(" ", "_"), 100)

    def _row_value(self, row: pd.Series, role: str) -> Optional[str]:
        role_columns = self._columns_for_role(row.index, role)
        for column in role_columns:
            value = self._clean_value(row.get(column))
            if value:
                return value
        return None

    def _paired_name_value(self, table: LoadedTable, row: pd.Series, id_column: str) -> Optional[str]:
        normalized_id_column = self._normalize_column(id_column)
        preferred_names: list[str] = []
        if "current" in normalized_id_column:
            preferred_names.extend(
                column
                for column in table.employee_name_columns
                if "current" in self._normalize_column(column)
            )
        preferred_names.extend(
            column for column in table.employee_name_columns if column not in preferred_names
        )
        for column in preferred_names:
            value = self._clean_value(row.get(column))
            if value:
                return value
        return None

    def _build_identity_index(self) -> None:
        candidates: dict[str, dict[str, list[tuple[int, str, str]]]] = defaultdict(
            lambda: defaultdict(list)
        )
        source_files: dict[str, set[str]] = defaultdict(set)
        position_ids: dict[str, set[str]] = defaultdict(set)

        for employee_id, references in self.employee_row_index.items():
            seen_references: set[tuple[str, int]] = set()
            for table_key, row_index in references:
                if (table_key, row_index) in seen_references:
                    continue
                seen_references.add((table_key, row_index))

                table = self.tables[table_key]
                row = table.dataframe.loc[row_index]
                rank = self._source_rank(table.logical_name)
                source_files[employee_id].add(table.source_file)

                matching_id_columns = [
                    column
                    for column in table.employee_id_columns
                    if self._normalize_identifier(row.get(column)) == employee_id
                ]
                for id_column in matching_id_columns:
                    name = self._paired_name_value(table, row, id_column)
                    if name:
                        candidates[employee_id]["name"].append((rank, name, table.source_file))

                for role in ("department", "designation", "office", "job_level"):
                    value = self._row_value(row, role)
                    if value:
                        candidates[employee_id][role].append((rank, value, table.source_file))

                for column in table.position_id_columns:
                    value = self._clean_value(row.get(column))
                    normalized = self._normalize_identifier(value)
                    if normalized:
                        position_ids[employee_id].add(value or normalized)

        for employee_id in self.employee_row_index:
            identity: dict[str, Any] = {
                "employee_id": self._display_employee_id(employee_id),
                "canonical_name": None,
                "name_aliases": [],
                "department": None,
                "designation": None,
                "office": None,
                "job_level": None,
                "position_ids": sorted(position_ids.get(employee_id, set())),
                "source_files": sorted(source_files.get(employee_id, set())),
            }

            for role, output_key in (
                ("name", "canonical_name"),
                ("department", "department"),
                ("designation", "designation"),
                ("office", "office"),
                ("job_level", "job_level"),
            ):
                values = candidates[employee_id].get(role, [])
                if not values:
                    continue
                values.sort(key=lambda item: (item[0], item[1].casefold()))
                identity[output_key] = values[0][1]

                if role == "name":
                    unique_names: list[str] = []
                    seen_names: set[str] = set()
                    for _, value, _ in values:
                        normalized_name = self._normalize_text(value)
                        if normalized_name and normalized_name not in seen_names:
                            seen_names.add(normalized_name)
                            unique_names.append(value)
                    identity["name_aliases"] = [
                        name
                        for name in unique_names
                        if self._normalize_text(name)
                        != self._normalize_text(identity["canonical_name"])
                    ]

            self.identities[employee_id] = identity

    def _display_employee_id(self, normalized_employee_id: str) -> str:
        references = self.employee_row_index.get(normalized_employee_id, [])
        for table_key, row_index in references:
            table = self.tables[table_key]
            row = table.dataframe.loc[row_index]
            for column in table.employee_id_columns:
                value = self._clean_value(row.get(column))
                if self._normalize_identifier(value) == normalized_employee_id:
                    return value or normalized_employee_id
        return normalized_employee_id

    @staticmethod
    def _candidate_view(identity: dict[str, Any]) -> dict[str, Any]:
        return {
            "employee_id": identity.get("employee_id"),
            "employee_name": identity.get("canonical_name"),
            "name_aliases": identity.get("name_aliases", []),
            "department": identity.get("department"),
            "designation": identity.get("designation"),
            "office": identity.get("office"),
            "job_level": identity.get("job_level"),
            "position_ids": identity.get("position_ids", []),
        }

    def _matches_optional_filter(
        self, identity: dict[str, Any], key: str, requested_value: Optional[str]
    ) -> bool:
        if not requested_value:
            return True

        requested = self._normalize_text(requested_value)
        if key == "position_id":
            return any(
                self._normalize_identifier(position_id)
                == self._normalize_identifier(requested_value)
                for position_id in identity.get("position_ids", [])
            )

        actual = self._normalize_text(identity.get(key))
        return bool(actual and requested in actual)

    def _search_name(
        self,
        employee_name: str,
        department: Optional[str],
        designation: Optional[str],
        position_id: Optional[str],
        office: Optional[str],
    ) -> tuple[list[str], str]:
        query = self._normalize_text(employee_name)
        if not query:
            return [], "none"

        exact: list[str] = []
        partial: list[str] = []
        fuzzy_matches: list[tuple[float, str]] = []

        query_tokens = set(query.split())
        for employee_id, identity in self.identities.items():
            names = [identity.get("canonical_name")] + list(identity.get("name_aliases", []))
            normalized_names = [self._normalize_text(name) for name in names if name]

            if query in normalized_names:
                exact.append(employee_id)
                continue

            if any(query_tokens and query_tokens.issubset(set(name.split())) for name in normalized_names):
                partial.append(employee_id)
                continue

            best_score = max((fuzz.WRatio(query, name) for name in normalized_names), default=0)
            if best_score >= 85:
                fuzzy_matches.append((float(best_score), employee_id))

        match_type = "exact_name"
        candidates = exact
        if not candidates:
            match_type = "partial_name"
            candidates = partial
        if not candidates:
            match_type = "fuzzy_name"
            fuzzy_matches.sort(reverse=True)
            candidates = [employee_id for _, employee_id in fuzzy_matches[:10]]

        filtered = []
        for employee_id in candidates:
            identity = self.identities[employee_id]
            if not self._matches_optional_filter(identity, "department", department):
                continue
            if not self._matches_optional_filter(identity, "designation", designation):
                continue
            if not self._matches_optional_filter(identity, "position_id", position_id):
                continue
            if not self._matches_optional_filter(identity, "office", office):
                continue
            filtered.append(employee_id)

        return filtered, match_type

    # ----------------------------- record fetch -----------------------------

    def _clean_row(self, row: pd.Series) -> dict[str, Optional[str]]:
        return {str(column): self._clean_value(value) for column, value in row.items()}

    @staticmethod
    def _row_signature(record: dict[str, Any]) -> str:
        normalized_record = {
            re.sub(r"[^a-z0-9]", "", str(key).casefold()): value
            for key, value in record.items()
            if not str(key).startswith("_")
        }
        return json.dumps(normalized_record, sort_keys=True, ensure_ascii=False)

    def _add_references(
        self,
        references: Iterable[tuple[str, int]],
        output: dict[str, list[dict[str, Any]]],
        seen_signatures: dict[str, dict[str, Any]],
        seen_row_references: set[tuple[str, int]],
        quality: dict[str, Any],
    ) -> None:
        for table_key, row_index in references:
            row_reference = (table_key, row_index)
            if row_reference in seen_row_references:
                continue
            seen_row_references.add(row_reference)

            table = self.tables[table_key]
            record = self._clean_row(table.dataframe.loc[row_index])
            signature = self._row_signature(record)

            if signature in seen_signatures:
                existing = seen_signatures[signature]
                if table.source_file not in existing["_source_files"]:
                    existing["_source_files"].append(table.source_file)
                    existing["_source_files"].sort()
                quality["exact_duplicate_rows_removed"] += 1
                continue

            record["_source_files"] = [table.source_file]
            seen_signatures[signature] = record
            output[table.logical_name].append(record)

    def _collect_related_ids(
        self, records: dict[str, list[dict[str, Any]]], role: str
    ) -> set[str]:
        collected: set[str] = set()
        for table_records in records.values():
            for record in table_records:
                for column, value in record.items():
                    if column.startswith("_"):
                        continue
                    if self._is_alias(column, role):
                        normalized = self._normalize_identifier(value)
                        if normalized:
                            collected.add(normalized)
        return collected

    def get_by_employee_id(self, employee_id: str, match_method: str = "employee_id") -> dict[str, Any]:
        normalized_employee_id = self._normalize_identifier(employee_id)
        if normalized_employee_id not in self.identities:
            return {
                "status": "not_found",
                "message": f"No employee was found with Employee ID '{employee_id}'.",
                "searched_employee_id": employee_id,
            }

        employee_records: dict[str, list[dict[str, Any]]] = defaultdict(list)
        position_records: dict[str, list[dict[str, Any]]] = defaultdict(list)
        skill_catalog_records: dict[str, list[dict[str, Any]]] = defaultdict(list)
        seen_signatures: dict[str, dict[str, Any]] = {}
        seen_row_references: set[tuple[str, int]] = set()
        quality: dict[str, Any] = {
            "csv_tables_scanned": len(self.tables),
            "exact_duplicate_rows_removed": 0,
            "unresolved_position_ids": [],
            "unresolved_skill_ids": [],
        }

        self._add_references(
            self.employee_row_index[normalized_employee_id],
            employee_records,
            seen_signatures,
            seen_row_references,
            quality,
        )

        position_ids = self._collect_related_ids(employee_records, "position_id")
        for position_id in sorted(position_ids):
            references = self.position_row_index.get(position_id, [])
            if not references:
                quality["unresolved_position_ids"].append(position_id)
                continue
            self._add_references(
                references,
                position_records,
                seen_signatures,
                seen_row_references,
                quality,
            )

        skill_ids = self._collect_related_ids(employee_records, "skill_id")
        skill_ids.update(self._collect_related_ids(position_records, "skill_id"))
        for skill_id in sorted(skill_ids):
            all_references = self.skill_row_index.get(skill_id, [])
            references = [
                reference
                for reference in all_references
                if not self.tables[reference[0]].employee_id_columns
                and not self.tables[reference[0]].position_id_columns
            ]
            if not references:
                quality["unresolved_skill_ids"].append(skill_id)
                continue
            self._add_references(
                references,
                skill_catalog_records,
                seen_signatures,
                seen_row_references,
                quality,
            )

        identity = dict(self.identities[normalized_employee_id])
        identity["employee_id"] = self._display_employee_id(normalized_employee_id)

        all_source_files: set[str] = set()
        for section in (employee_records, position_records, skill_catalog_records):
            for records in section.values():
                for record in records:
                    all_source_files.update(record.get("_source_files", []))

        # Do not expose prediction labels to the LLM or the prediction tool.
        excluded_fields = {
            "Will_Resign_in_Next_6_Months",
            "Attrition_Label_Reference",
            "Vacancy_Planning_Status",
        }

        def clean_record(record: dict[str, Any]) -> dict[str, Any]:
            return {
                key: value
                for key, value in record.items()
                if key not in excluded_fields and not key.startswith("_")
            }

        def first_record(
            section: dict[str, list[dict[str, Any]]],
            *table_names: str,
        ) -> dict[str, Any]:
            for table_name in table_names:
                rows = section.get(table_name, [])
                if rows:
                    return clean_record(rows[0])
            return {}

        def all_records(
            section: dict[str, list[dict[str, Any]]],
            table_name: str,
        ) -> list[dict[str, Any]]:
            return [clean_record(row) for row in section.get(table_name, [])]

        missing_relations = [
            {"relation": "position_id", "value": value}
            for value in quality["unresolved_position_ids"]
        ]
        missing_relations.extend(
            {"relation": "skill_id", "value": value}
            for value in quality["unresolved_skill_ids"]
        )

        return {
            "status": "found",
            "match_method": match_method,
            "employee": {
                "employee_id": identity.get("employee_id"),
                "employee_name": identity.get("canonical_name"),
                "name_aliases": identity.get("name_aliases", []),
                "department": identity.get("department"),
                "designation": identity.get("designation"),
                "office": identity.get("office"),
                "job_level": identity.get("job_level"),
                "position_ids": identity.get("position_ids", []),
            },
            "records": {
                "profile": first_record(employee_records, "Employee_Profile"),
                "attendance": first_record(employee_records, "Employee_Attendance"),
                "performance": first_record(employee_records, "Employee_Performance"),
                "experience": first_record(employee_records, "Employee_Experience"),
                "skills": all_records(employee_records, "Employee_Skills"),
                "attrition_features": first_record(
                    employee_records,
                    "Final_Attrition_Dataset_200_Employees",
                    "Source_Attrition_Data",
                ),
                "position": first_record(employee_records, "Position_Master"),
                "position_requirements": first_record(
                    employee_records,
                    "Position_Requirements",
                ),
                "position_skill_requirements": all_records(
                    position_records,
                    "Position_Skill_Requirements",
                ),
                "skill_catalog": all_records(
                    skill_catalog_records,
                    "Skill_Catalog",
                ),
            },
            "data_quality": {
                "duplicates_removed": quality["exact_duplicate_rows_removed"],
                "conflicts": [],
                "missing_relations": missing_relations,
                "csv_tables_scanned": quality["csv_tables_scanned"],
                "source_files_returned": sorted(all_source_files),
            },
        }

    def search(
        self,
        employee_id: Optional[str] = None,
        employee_name: Optional[str] = None,
        department: Optional[str] = None,
        designation: Optional[str] = None,
        position_id: Optional[str] = None,
        office: Optional[str] = None,
    ) -> dict[str, Any]:
        if employee_id:
            return self.get_by_employee_id(employee_id, match_method="employee_id")

        if not employee_name:
            return {
                "status": "invalid_request",
                "message": "Provide either employee_id or employee_name.",
            }

        candidates, match_type = self._search_name(
            employee_name=employee_name,
            department=department,
            designation=designation,
            position_id=position_id,
            office=office,
        )

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

        # Fuzzy matches always require confirmation to avoid returning the wrong employee.
        if len(candidates) > 1 or match_type == "fuzzy_name":
            return {
                "status": "needs_clarification",
                "match_method": match_type,
                "message": (
                    "Multiple or approximate employee matches were found. Ask the user to "
                    "select the correct employee, preferably by Employee ID."
                ),
                "candidates": [self._candidate_view(self.identities[item]) for item in candidates],
                "next_action": (
                    "Ask which employee is intended, then call this tool again with employee_id."
                ),
            }

        return self.get_by_employee_id(candidates[0], match_method=match_type)


# ---------------------------------------------------------------------------
# LangChain tool factory
# ---------------------------------------------------------------------------


def create_employee_record_tool(data_path: str | Path) -> "BaseTool":
    """Create a LangChain tool bound to a folder, CSV, or ZIP data source."""

    repository = EmployeeRecordRepository(data_path)

    @tool(args_schema=EmployeeRecordSearchInput)
    def get_employee_record(
        employee_id: Optional[str] = None,
        employee_name: Optional[str] = None,
        department: Optional[str] = None,
        designation: Optional[str] = None,
        position_id: Optional[str] = None,
        office: Optional[str] = None,
    ) -> dict[str, Any]:
        """Retrieve one employee's complete HR record from all related CSV files.

        Prefer employee_id when the user supplies one. When searching by name,
        include department, designation, position_id, or office if the user
        mentioned them. Never guess between multiple candidates. The tool joins
        direct employee records through Employee_ID or Current_Employee_ID,
        follows the employee's Position_ID into position tables, follows Skill_ID
        into skill catalog tables, removes exact duplicate rows, and returns one
        structured JSON object. It performs no attrition prediction.
        """

        return repository.search(
            employee_id=employee_id,
            employee_name=employee_name,
            department=department,
            designation=designation,
            position_id=position_id,
            office=office,
        )

    # `tool` is resolved through the try/except above, so a type checker
    # binds it to the no-langchain fallback and cannot see that the
    # decorator returns a BaseTool.
    return cast("BaseTool", get_employee_record)


EMPLOYEE_RECORD_TOOL_INSTRUCTIONS = """
You are an HR reasoning assistant with access to get_employee_record.

Rules:
1. When the user asks about a specific employee, extract employee_id when present;
   otherwise extract employee_name. Also pass department, designation, position_id,
   or office only when explicitly available in the conversation.
2. Prefer Employee ID because it is the unique identity key. Never invent an ID.
3. Call get_employee_record before making any factual statement about the employee.
4. Read the tool status:
   - found: use only the returned employee and records as factual HR data.
   - needs_clarification: do not choose a candidate yourself. Ask the user which
     listed employee they mean, showing Employee ID and useful context.
   - not_found: ask the user to verify the name or Employee ID.
   - invalid_request: ask for a name or Employee ID.
5. Employee names may differ across source files. Records are joined by employee ID,
   not by name. Treat name_aliases as alternate names for the same employee ID.
6. Do not treat multiple skill, attendance-period, performance-period, or experience
   rows as duplicates. The tool already removes only exact duplicate rows.
7. Do not make an attrition prediction from this retrieval tool. It only returns data.
""".strip()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Test the employee record retrieval tool")
    parser.add_argument("data_path", help="Folder, CSV, or ZIP containing HR CSV data")
    parser.add_argument("--employee-id", dest="employee_id")
    parser.add_argument("--employee-name", dest="employee_name")
    parser.add_argument("--department")
    parser.add_argument("--designation")
    parser.add_argument("--position-id", dest="position_id")
    parser.add_argument("--office")
    arguments = parser.parse_args()

    test_tool = create_employee_record_tool(arguments.data_path)
    result = test_tool.invoke(
        {
            "employee_id": arguments.employee_id,
            "employee_name": arguments.employee_name,
            "department": arguments.department,
            "designation": arguments.designation,
            "position_id": arguments.position_id,
            "office": arguments.office,
        }
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
