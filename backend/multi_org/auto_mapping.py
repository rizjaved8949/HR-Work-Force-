"""Conservative automatic mapping for the one-click organization sync flow.

The normal Step-12 review APIs remain available.  This module is used only by
``auto-sync`` and accepts a mapping without a human click *only* when it can be
constructed from explicit aliases / confirmed ontology aliases and passes the
existing MappingPlanValidator.

Unknown columns are deliberately left unmapped.  They are still preserved in
the raw Supabase ingestion tables by :mod:`multi_org.supabase_ingestion_store`.
"""
from __future__ import annotations

import itertools
import os
from dataclasses import dataclass
from typing import Any

from graph.schema import DEFAULT_GRAPH_SCHEMA, GraphSchema
from ingestion.mapper import DEFAULT_MAPPING_SUGGESTER, OntologyMappingSuggester, normalize_name
from ingestion.models import EntityIngestionRule, PropertyMapping, RelationshipMapping, SourceSchemaProfile
from mapping.registry import DEFAULT_MAPPING_REGISTRY, MappingRegistry
from ontology.registry import DEFAULT_REGISTRY, OntologyRegistry


# Explicit multi-organization aliases.  These are intentionally narrow.  They
# cover common HR exports without treating arbitrary fuzzy matches as truth.
_EXPLICIT_ALIASES: dict[str, str] = {
    # Organization / structure
    "orgcode": "Organization.organizationId",
    "orgid": "Organization.organizationId",
    "organizationcode": "Organization.organizationId",
    "organizationid": "Organization.organizationId",
    "companycode": "Organization.organizationId",
    "companyid": "Organization.organizationId",
    "companyname": "Organization.name",
    "organizationname": "Organization.name",
    "orgname": "Organization.name",
    "businessunitid": "BusinessUnit.businessUnitId",
    "businessunitcode": "BusinessUnit.businessUnitId",
    # When an export only has the BU label, use that stable source value as its
    # tenant-scoped business identity rather than inventing a second value.
    "businessunit": "BusinessUnit.businessUnitId",
    "divisionid": "Department.departmentId",
    "divisioncode": "Department.departmentId",
    "division": "Department.departmentId",
    "departmentid": "Department.departmentId",
    "departmentcode": "Department.departmentId",
    "department": "Department.departmentId",
    "departmentname": "Department.name",
    "teamid": "OrganizationalUnit.organizationalUnitId",
    "teamcode": "OrganizationalUnit.organizationalUnitId",
    "team": "OrganizationalUnit.organizationalUnitId",
    # Employee / employment
    "staffno": "Employee.employeeId",
    "staffnumber": "Employee.employeeId",
    "staffid": "Employee.employeeId",
    "employeeno": "Employee.employeeId",
    "employeenumber": "Employee.employeeId",
    "employeeid": "Employee.employeeId",
    "empid": "Employee.employeeId",
    "empcode": "Employee.employeeId",
    "workercode": "Employee.employeeId",
    "workerid": "Employee.employeeId",
    "personnelno": "Employee.employeeId",
    "workername": "Employee.name",
    "staffname": "Employee.name",
    "employeename": "Employee.name",
    "fullname": "Employee.name",
    "joinedon": "Employment.hireDate",
    "joindate": "Employment.hireDate",
    "dateofjoining": "Employment.hireDate",
    "hiredate": "Employment.hireDate",
    "empstatus": "Employment.employeeStatus",
    "employeestatus": "Employment.employeeStatus",
    "employmentstatus": "Employment.employeeStatus",
    "dataasof": "Employment.dataAsOfDate",
    "dataasofdate": "Employment.dataAsOfDate",
    # Position
    "positioncode": "Position.positionId",
    "positionid": "Position.positionId",
    "jobcode": "Position.positionId",
    "rolecode": "Position.positionId",
    "positiontitle": "Position.title",
    "jobtitle": "Position.title",
    "designation": "Position.designation",
    # Compensation / experience / performance / attendance / engagement
    "currency": "CompensationRecord.currency",
    "monthlyincomepkr": "CompensationRecord.monthlyAmount",
    "monthlysalarypkr": "CompensationRecord.monthlyAmount",
    "monthlysalary": "CompensationRecord.monthlyAmount",
    "salarymarketgappct": "CompensationRecord.salaryVsMarketPercentage",
    "salaryvsmarketpct": "CompensationRecord.salaryVsMarketPercentage",
    "lastraisepct": "CompensationRecord.lastIncrementPercentage",
    "lastincrementpct": "CompensationRecord.lastIncrementPercentage",
    "payconcernrecent": "CompensationRecord.payConcernRaisedLast6Months",
    "payconcernraisedlast6m": "CompensationRecord.payConcernRaisedLast6Months",
    "monthssincepromotion": "ExperienceProfile.monthsSinceLastPromotion",
    "monthssincelastpromotion": "ExperienceProfile.monthsSinceLastPromotion",
    "kpiscorepct": "PerformanceRecord.kpiAchievementPercentage",
    "kpiachievementpct": "PerformanceRecord.kpiAchievementPercentage",
    "overtimelast30d": "AttendanceRecord.overtimeHoursLast30Days",
    "overtimehourslast30d": "AttendanceRecord.overtimeHoursLast30Days",
    "engagementrating": "EngagementRecord.engagementScore",
    "engagementscore": "EngagementRecord.engagementScore",
    "jobsatisfaction": "EngagementRecord.jobSatisfactionScore",
    "jobsatisfactionscore": "EngagementRecord.jobSatisfactionScore",
    "worklifebalance": "EngagementRecord.workLifeBalanceScore",
    "worklifebalancescore": "EngagementRecord.workLifeBalanceScore",
    "managerrelationscore": "EngagementRecord.managerRelationshipScore",
    "managerrelationshipscore": "EngagementRecord.managerRelationshipScore",
    "careergrowthrating": "EngagementRecord.careerGrowthScore",
    "careergrowthscore": "EngagementRecord.careerGrowthScore",
    # Skills
    "primaryskill": "Skill.skillId",
    "skillid": "Skill.skillId",
    "skillcode": "Skill.skillId",
    "skillname": "Skill.name",
    "skillproficiency": "EmployeeSkill.proficiencyLabel",
    "proficiencylabel": "EmployeeSkill.proficiencyLabel",
    "proficiencylevel": "EmployeeSkill.proficiencyLevel",
}


# Relations that are safe when both endpoints are produced from the same source
# row.  Deliberately excludes leadership / ownership / scenario relations that
# would require extra semantic evidence.
_SAFE_SAME_ROW_RELATIONS: tuple[tuple[str, str, str], ...] = (
    ("Organization", "HAS_BUSINESS_UNIT", "BusinessUnit"),
    ("BusinessUnit", "HAS_DEPARTMENT", "Department"),
    ("Department", "HAS_ORGANIZATIONAL_UNIT", "OrganizationalUnit"),
    ("Employee", "HAS_EMPLOYMENT", "Employment"),
    ("Employment", "WORKS_FOR", "Organization"),
    ("Employee", "HAS_ASSIGNMENT", "Assignment"),
    ("Assignment", "TO_POSITION", "Position"),
    ("Assignment", "IN_DEPARTMENT", "Department"),
    ("Assignment", "IN_ORGANIZATIONAL_UNIT", "OrganizationalUnit"),
    ("Assignment", "AT_LOCATION", "WorkLocation"),
    ("Assignment", "CHARGED_TO", "CostCenter"),
    ("Position", "IN_DEPARTMENT", "Department"),
    ("Position", "AT_LOCATION", "WorkLocation"),
    ("Position", "CHARGED_TO", "CostCenter"),
    ("Employee", "HAS_COMPENSATION", "CompensationRecord"),
    ("Employee", "HAS_EXPERIENCE_PROFILE", "ExperienceProfile"),
    ("Employee", "HAS_ENGAGEMENT_RECORD", "EngagementRecord"),
    ("Employee", "HAS_PERFORMANCE_RECORD", "PerformanceRecord"),
    ("Employee", "HAS_PERFORMANCE_SUMMARY", "PerformanceSummary"),
    ("Employee", "HAS_ATTENDANCE_RECORD", "AttendanceRecord"),
    ("Employee", "HAS_SKILL", "EmployeeSkill"),
    ("EmployeeSkill", "OF_SKILL", "Skill"),
    ("Position", "HAS_REQUIREMENT", "PositionRequirement"),
    ("Position", "REQUIRES_SKILL", "PositionSkillRequirement"),
    ("PositionSkillRequirement", "OF_SKILL", "Skill"),
    ("Employee", "HAS_LEARNING_RECORD", "LearningRecord"),
    ("LearningRecord", "FOR_COURSE", "LearningCourse"),
    ("LearningRecord", "DEVELOPS_SKILL", "Skill"),
    ("LearningCourse", "DEVELOPS_SKILL", "Skill"),
    ("Employee", "HAS_CAREER_MOVEMENT", "CareerMovement"),
    ("Employee", "HAS_SUCCESSION_READINESS", "SuccessionReadiness"),
    ("Position", "HAS_VACANCY", "VacancyRecord"),
    ("Department", "HAS_HEADCOUNT_SNAPSHOT", "HeadcountSnapshot"),
    ("Department", "HAS_DAILY_WORKFORCE_ACTIVITY", "DailyWorkforceActivity"),
    ("Department", "HAS_BUDGET", "DepartmentBudget"),
    ("Position", "HAS_BUDGET", "PositionBudget"),
    ("Department", "HAS_DEMAND_DRIVER", "WorkforceDemandDriver"),
    ("Department", "HAS_HEADCOUNT_EXCEPTION", "HeadcountException"),
)


@dataclass(frozen=True)
class AutoMappingBuild:
    property_mappings: list[PropertyMapping]
    entity_rules: list[EntityIngestionRule]
    relationship_mappings: list[RelationshipMapping]
    mapped_columns: list[str]
    unmapped_columns: list[str]
    skipped_pending_semantic_columns: list[str]
    dropped_entities_missing_identity: list[str]
    relationship_reference_columns: list[str]

    def summary(self) -> dict[str, Any]:
        """Return the mapping in a UI-friendly and audit-friendly shape.

        The one-click flow must make its automatic decisions visible.  We expose
        both the short column lists and the exact source -> ontology / typed-edge
        choices so the Live Response never hides what was written to the graph.
        """
        return {
            "mapped_column_count": len(self.mapped_columns),
            "mapped_columns": self.mapped_columns,
            "unmapped_column_count": len(self.unmapped_columns),
            "unmapped_columns": self.unmapped_columns,
            "skipped_pending_semantic_columns": self.skipped_pending_semantic_columns,
            "dropped_entities_missing_identity": self.dropped_entities_missing_identity,
            "property_mapping_count": len(self.property_mappings),
            "property_mappings": [
                item.model_dump(mode="json") for item in self.property_mappings
            ],
            "entity_rule_count": len(self.entity_rules),
            "entity_rules": [item.model_dump(mode="json") for item in self.entity_rules],
            "relationship_mapping_count": len(self.relationship_mappings),
            "relationship_mappings": [
                item.model_dump(mode="json") for item in self.relationship_mappings
            ],
            "relationship_reference_columns": self.relationship_reference_columns,
        }


class AutoMappingBuilder:
    def __init__(
        self,
        *,
        ontology: OntologyRegistry = DEFAULT_REGISTRY,
        graph_schema: GraphSchema = DEFAULT_GRAPH_SCHEMA,
        suggester: OntologyMappingSuggester = DEFAULT_MAPPING_SUGGESTER,
        mapping_registry: MappingRegistry = DEFAULT_MAPPING_REGISTRY,
        minimum_fuzzy_confidence: float | None = None,
    ) -> None:
        self.ontology = ontology
        self.graph_schema = graph_schema
        self.suggester = suggester
        self.mapping_registry = mapping_registry
        self.minimum_fuzzy_confidence = (
            float(minimum_fuzzy_confidence)
            if minimum_fuzzy_confidence is not None
            else float(os.getenv("MULTI_ORG_AUTO_MAP_MIN_CONFIDENCE", "0.94"))
        )
        self._confirmed_aliases = self._build_confirmed_alias_index()

    def _build_confirmed_alias_index(self) -> dict[str, str]:
        candidates: dict[str, set[str]] = {}
        try:
            payload = self.mapping_registry.load()
        except Exception:
            return {}
        for dataset in payload.get("datasets", []):
            for item in dataset.get("columns", []):
                if item.get("disposition") not in {"direct_property", "context_property"}:
                    continue
                path = item.get("ontology_path")
                source = item.get("source_column")
                if not path or not source:
                    continue
                try:
                    prop = self.ontology.get_property(path)
                except KeyError:
                    continue
                if prop.semantic_status != "confirmed":
                    continue
                candidates.setdefault(normalize_name(source), set()).add(path)
        # Only aliases that mean one thing across the current source corpus are
        # eligible for automatic reuse.
        return {
            key: next(iter(paths))
            for key, paths in candidates.items()
            if len(paths) == 1
        }

    @staticmethod
    def _norm_key(value: str) -> str:
        return normalize_name(value)

    @staticmethod
    def _column_values(rows: list[dict[str, Any]], column: str) -> list[str]:
        values: list[str] = []
        for row in rows:
            raw = row.get(column)
            values.append("" if raw is None else str(raw).strip())
        return values

    @classmethod
    def _is_complete(cls, rows: list[dict[str, Any]], columns: list[str]) -> bool:
        return bool(rows) and all(
            all(str(row.get(column) if row.get(column) is not None else "").strip() for column in columns)
            for row in rows
        )

    @classmethod
    def _is_unique_combo(cls, rows: list[dict[str, Any]], columns: list[str]) -> bool:
        if not columns or not cls._is_complete(rows, columns):
            return False
        keys = [tuple(str(row.get(c)).strip() for c in columns) for row in rows]
        return len(keys) == len(set(keys))

    def _best_record_key(
        self,
        entity_type: str,
        rows: list[dict[str, Any]],
        profile: SourceSchemaProfile,
        source_by_path: dict[str, str],
    ) -> list[str]:
        # Prefer meaningful parent/business keys plus time dimensions.  This
        # keeps re-uploaded records stable when the source rows are reordered.
        preferred_paths: dict[str, tuple[str, ...]] = {
            "Employment": ("Employee.employeeId",),
            "CompensationRecord": ("Employee.employeeId",),
            "ExperienceProfile": ("Employee.employeeId",),
            "PerformanceRecord": ("Employee.employeeId",),
            "PerformanceSummary": ("Employee.employeeId",),
            "AttendanceRecord": ("Employee.employeeId",),
            "EngagementRecord": ("Employee.employeeId",),
            "SuccessionReadiness": ("Employee.employeeId",),
            "EmployeeSkill": ("Employee.employeeId", "Skill.skillId"),
            "PositionRequirement": ("Position.positionId",),
            "PositionSkillRequirement": ("Position.positionId", "Skill.skillId"),
            "HeadcountSnapshot": ("Department.departmentId",),
            "DailyWorkforceActivity": ("Department.departmentId",),
        }
        keys = [source_by_path[p] for p in preferred_paths.get(entity_type, ()) if p in source_by_path]
        temporal = [
            c.name for c in profile.columns
            if any(token in self._norm_key(c.name) for token in ("dataasof", "date", "period", "month", "year"))
        ]
        # If the preferred business keys are already unique, use them.  For
        # snapshot-style rows prefer a temporal discriminator when available.
        if keys:
            for t in temporal:
                combo = list(dict.fromkeys(keys + [t]))
                if self._is_unique_combo(rows, combo):
                    return combo
            if self._is_unique_combo(rows, keys):
                return keys
            # Even when not unique in a sample, business+time is semantically
            # more stable than a random fuzzy column.
            for t in temporal:
                combo = list(dict.fromkeys(keys + [t]))
                if self._is_complete(rows, combo):
                    return combo
            if self._is_complete(rows, keys):
                return keys

        # Generic fallback: try fully-populated ID/code/key columns first.
        candidate_columns = [
            c.name for c in profile.columns
            if any(tok in self._norm_key(c.name) for tok in ("id", "code", "number", "no", "key"))
        ]
        candidate_columns += [c for c in temporal if c not in candidate_columns]
        for size in (1, 2, 3):
            for combo in itertools.combinations(candidate_columns[:12], size):
                if self._is_unique_combo(rows, list(combo)):
                    return list(combo)
        return []

    def _choose_reference_column(self, profile: SourceSchemaProfile, kind: str) -> str | None:
        for column in profile.columns:
            norm = self._norm_key(column.name)
            if kind == "employee_manager":
                if ("manager" in norm or "supervisor" in norm or "reportingmanager" in norm) and any(
                    token in norm for token in ("id", "no", "number", "code", "staff", "employee")
                ):
                    return column.name
            if kind == "position_manager":
                if "reportingposition" in norm or ("parentposition" in norm):
                    return column.name
        return None

    def build(self, profile: SourceSchemaProfile, rows: list[dict[str, Any]]) -> AutoMappingBuild:
        choices: list[tuple[str, str, float, str]] = []
        pending_skipped: list[str] = []
        all_columns = [c.name for c in profile.columns]

        for column in profile.columns:
            norm = self._norm_key(column.name)
            path: str | None = None
            confidence = 0.0
            strategy = ""
            alias_key = norm.replace(" ", "")
            if alias_key in _EXPLICIT_ALIASES:
                path = _EXPLICIT_ALIASES[alias_key]
                confidence = 1.0
                strategy = "explicit_multi_org_alias"
            elif norm in self._confirmed_aliases:
                path = self._confirmed_aliases[norm]
                confidence = 0.99
                strategy = "confirmed_current_source_alias"
            else:
                proposal = self.suggester.propose_column(column.name, column.observed_type)
                candidate = proposal.candidates[0] if proposal.candidates else None
                if (
                    candidate
                    and candidate.confidence >= self.minimum_fuzzy_confidence
                    and candidate.semantic_status == "confirmed"
                    and candidate.type_compatible is not False
                ):
                    path = candidate.ontology_path
                    confidence = candidate.confidence
                    strategy = candidate.match_strategy
                elif candidate and candidate.semantic_status != "confirmed":
                    pending_skipped.append(column.name)

            if not path:
                continue
            try:
                prop = self.ontology.get_property(path)
            except KeyError:
                continue
            if prop.semantic_status != "confirmed":
                pending_skipped.append(column.name)
                continue
            choices.append((column.name, path, confidence, strategy))

        # One source -> one property and one property <- one source.  Prefer the
        # highest-confidence source when two columns could populate the same path.
        best_by_path: dict[str, tuple[str, str, float, str]] = {}
        for item in choices:
            previous = best_by_path.get(item[1])
            if previous is None or (item[2], item[0]) > (previous[2], previous[0]):
                best_by_path[item[1]] = item
        selected = list(best_by_path.values())

        # Remove entity mappings that cannot satisfy the graph's stable identity
        # rule.  Raw columns remain persisted and are reported as unmapped.
        paths = {item[1] for item in selected}
        entities = {path.split(".", 1)[0] for path in paths}
        dropped_entities: list[str] = []
        for entity_type in sorted(entities):
            rule = self.graph_schema.identity_rule(entity_type)
            if rule.get("mode") == "ontology_property":
                identity_path = f"{entity_type}.{rule.get('property')}"
                if identity_path not in paths:
                    dropped_entities.append(entity_type)
        if dropped_entities:
            selected = [item for item in selected if item[1].split(".", 1)[0] not in set(dropped_entities)]

        property_mappings = [PropertyMapping(source_column=src, ontology_path=path) for src, path, _, _ in selected]
        mapped_columns = sorted({item.source_column for item in property_mappings})
        source_by_path = {item.ontology_path: item.source_column for item in property_mappings}
        mapped_entities = {item.ontology_path.split(".", 1)[0] for item in property_mappings}

        entity_rules: list[EntityIngestionRule] = []
        for entity_type in sorted(mapped_entities):
            identity = self.graph_schema.identity_rule(entity_type)
            if identity.get("mode") == "ontology_property":
                continue
            record_keys = self._best_record_key(entity_type, rows, profile, source_by_path)
            if not record_keys:
                # Without a deterministic record key, drop this record-like entity
                # rather than inventing a row identity.
                dropped_entities.append(entity_type)
                continue
            valid_from = next(
                (
                    c.name for c in profile.columns
                    if self._norm_key(c.name).replace(" ", "") in {"dataasof", "dataasofdate", "effectivedate", "assessmentdate"}
                ),
                None,
            )
            entity_rules.append(
                EntityIngestionRule(
                    entity_type=entity_type,
                    record_key_columns=record_keys,
                    valid_from_column=valid_from,
                )
            )

        if dropped_entities:
            dropped_set = set(dropped_entities)
            property_mappings = [
                item for item in property_mappings
                if item.ontology_path.split(".", 1)[0] not in dropped_set
            ]
            mapped_entities = {item.ontology_path.split(".", 1)[0] for item in property_mappings}
            entity_rules = [item for item in entity_rules if item.entity_type in mapped_entities]
            mapped_columns = sorted({item.source_column for item in property_mappings})

        relationships: list[RelationshipMapping] = []
        for source, relation, target in _SAFE_SAME_ROW_RELATIONS:
            if source in mapped_entities and target in mapped_entities and self.graph_schema.allowed_relationship(source, relation, target):
                relationships.append(
                    RelationshipMapping(
                        relation_type=relation,
                        source_entity_type=source,
                        target_entity_type=target,
                        target_mode="same_row_entity",
                    )
                )

        reference_columns: list[str] = []
        if "Employee" in mapped_entities:
            manager_col = self._choose_reference_column(profile, "employee_manager")
            if manager_col and self.graph_schema.allowed_relationship("Employee", "REPORTS_TO", "Employee"):
                relationships.append(
                    RelationshipMapping(
                        relation_type="REPORTS_TO",
                        source_entity_type="Employee",
                        target_entity_type="Employee",
                        target_mode="business_id_reference",
                        target_source_column=manager_col,
                        skip_if_empty=True,
                    )
                )
                reference_columns.append(manager_col)
        if "Position" in mapped_entities:
            reporting_col = self._choose_reference_column(profile, "position_manager")
            if reporting_col and self.graph_schema.allowed_relationship("Position", "REPORTS_TO_POSITION", "Position"):
                relationships.append(
                    RelationshipMapping(
                        relation_type="REPORTS_TO_POSITION",
                        source_entity_type="Position",
                        target_entity_type="Position",
                        target_mode="business_id_reference",
                        target_source_column=reporting_col,
                        skip_if_empty=True,
                    )
                )
                reference_columns.append(reporting_col)

        unmapped_columns = sorted(set(all_columns) - set(mapped_columns) - set(reference_columns))
        return AutoMappingBuild(
            property_mappings=property_mappings,
            entity_rules=entity_rules,
            relationship_mappings=relationships,
            mapped_columns=mapped_columns,
            unmapped_columns=unmapped_columns,
            skipped_pending_semantic_columns=sorted(set(pending_skipped)),
            dropped_entities_missing_identity=sorted(set(dropped_entities)),
            relationship_reference_columns=sorted(set(reference_columns)),
        )


DEFAULT_AUTO_MAPPING_BUILDER = AutoMappingBuilder()
