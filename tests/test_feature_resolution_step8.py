from __future__ import annotations

import ast
import math
from pathlib import Path

import pytest


def _existing_attrition_feature_order():
    source = (Path(__file__).resolve().parents[1] / "backend" / "attrition_prediction_tool.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "EXPECTED_FEATURES":
                    return ast.literal_eval(node.value)
    raise AssertionError("EXPECTED_FEATURES not found in existing attrition_prediction_tool.py")


EXPECTED_FEATURES = _existing_attrition_feature_order()
from feature_resolution.adapters import FeatureResolutionBlockedError
from feature_resolution.models import ResolutionMethod, ResolutionStatus
from feature_resolution.providers import MappingValueProvider
from feature_resolution.registry import DEFAULT_FEATURE_CONTRACTS
from feature_resolution.resolver import DEFAULT_FEATURE_RESOLVER
from feature_resolution.service import FeatureResolutionService
from graph.memory_repository import InMemoryGraphRepository
from graph.service import GRAPH_MODEL_SERVICE
from semantic.service import SemanticHRService


def _node(repo, *, entity_type, properties, key, tenant="ORG-1"):
    node = GRAPH_MODEL_SERVICE.create_node(
        tenant_id=tenant,
        entity_type=entity_type,
        properties=properties,
        source_system="step8-test",
        source_object=entity_type.lower(),
        source_record_key=key,
        mapping_version="step8-test",
    )
    repo.upsert_node(node)
    return node


def _edge(repo, source, relation, target, *, key, tenant="ORG-1"):
    edge = GRAPH_MODEL_SERVICE.create_relationship(
        tenant_id=tenant,
        relation_type=relation,
        source_node=source,
        target_node=target,
        source_system="step8-test",
        source_object="relationship",
        source_record_key=key,
        mapping_version="step8-test",
    )
    repo.upsert_relationship(edge)
    return edge


def _seed_attrition_context(*, omit: set[str] | None = None, derive_tenure: bool = False):
    omit = omit or set()
    repo = InMemoryGraphRepository()
    employee = _node(
        repo,
        entity_type="Employee",
        properties={"employeeId": "E-1", "name": "Ali"},
        key="E-1",
    )

    employment_props = {
        "hireDate": "2025-01-15",
        "dataAsOfDate": "2026-03-15",
    }
    if not derive_tenure and "Employment.tenureMonths" not in omit:
        employment_props["tenureMonths"] = 14
    employment = _node(repo, entity_type="Employment", properties=employment_props, key="emp")

    compensation_props = {
        "monthlyAmount": 120000,
        "salaryVsMarketPercentage": -5.5,
        "lastIncrementPercentage": 8.0,
        "payConcernRaisedLast6Months": True,
    }
    experience_props = {"monthsSinceLastPromotion": 7}
    performance_props = {
        "assessmentPeriod": "2026-03",
        "kpiAchievementPercentage": 92.0,
        "performanceTrend6M": 3.5,
    }
    attendance_props = {
        "attendancePeriod": "2026-03",
        "overtimeHoursLast30Days": 12.0,
    }
    engagement_props = {
        "engagementScore": 4.1,
        "jobSatisfactionScore": 4.0,
        "workLifeBalanceScore": 3.8,
        "managerRelationshipScore": 4.2,
        "careerGrowthScore": 3.9,
        "dataAsOfDate": "2026-03-15",
    }

    entity_props = {
        "CompensationRecord": compensation_props,
        "ExperienceProfile": experience_props,
        "PerformanceRecord": performance_props,
        "AttendanceRecord": attendance_props,
        "EngagementRecord": engagement_props,
    }
    for path in omit:
        if "." not in path:
            continue
        entity, prop = path.split(".", 1)
        if entity == "Employment":
            employment_props.pop(prop, None)
        elif entity in entity_props:
            entity_props[entity].pop(prop, None)

    compensation = _node(repo, entity_type="CompensationRecord", properties=compensation_props, key="comp")
    experience = _node(repo, entity_type="ExperienceProfile", properties=experience_props, key="exp")
    performance = _node(repo, entity_type="PerformanceRecord", properties=performance_props, key="perf")
    attendance = _node(repo, entity_type="AttendanceRecord", properties=attendance_props, key="att")
    engagement = _node(repo, entity_type="EngagementRecord", properties=engagement_props, key="eng")

    _edge(repo, employee, "HAS_EMPLOYMENT", employment, key="employment")
    _edge(repo, employee, "HAS_COMPENSATION", compensation, key="compensation")
    _edge(repo, employee, "HAS_EXPERIENCE_PROFILE", experience, key="experience")
    _edge(repo, employee, "HAS_PERFORMANCE_RECORD", performance, key="performance")
    _edge(repo, employee, "HAS_ATTENDANCE_RECORD", attendance, key="attendance")
    _edge(repo, employee, "HAS_ENGAGEMENT_RECORD", engagement, key="engagement")
    return repo


def _service(repo=None):
    return FeatureResolutionService(SemanticHRService(repo or _seed_attrition_context()))


def test_attrition_contract_matches_existing_saved_model_feature_order():
    contract = DEFAULT_FEATURE_CONTRACTS.get("attrition")
    assert [item.feature_name for item in contract.ordered_features()] == EXPECTED_FEATURES
    assert len(contract.features) == 14


def test_attrition_all_current_graph_features_resolve_directly():
    report = _service().resolve_attrition(tenant_id="ORG-1", employee_id="E-1")
    assert report.feature_count == 14
    assert report.direct_count == 14
    assert report.derived_count == 0
    assert report.missing_count == 0
    # Performance_Trend_6M is intentionally still pending semantic scale confirmation.
    assert report.status == ResolutionStatus.READY_WITH_WARNINGS
    trend = next(item for item in report.features if item.feature_name == "Performance_Trend_6M")
    assert "semantic_status_pending_confirmation" in trend.warning_codes


def test_tenure_is_derived_only_from_approved_ontology_rule_when_direct_value_missing():
    service = _service(_seed_attrition_context(derive_tenure=True))
    report = service.resolve_attrition(tenant_id="ORG-1", employee_id="E-1")
    tenure = next(item for item in report.features if item.feature_name == "Tenure_Months")
    assert tenure.method == ResolutionMethod.DERIVED
    assert tenure.value == 14
    assert tenure.derivation_rule == "derive_tenure_months_from_hire_date"
    assert report.derived_count == 1
    assert report.missing_count == 0


def test_missing_attrition_feature_is_visible_and_preserves_model_native_missing_policy():
    repo = _seed_attrition_context(omit={"EngagementRecord.careerGrowthScore"})
    service = _service(repo)
    report = service.resolve_attrition(tenant_id="ORG-1", employee_id="E-1")
    assert report.status == ResolutionStatus.DEGRADED
    assert report.model_native_missing_count == 1
    assert report.critical_missing_count == 0

    envelope = service.attrition_adapter.adapt(report)
    assert envelope.ready is True
    assert envelope.unresolved_features == ["Career_Growth_Score"]
    assert math.isnan(envelope.values["Career_Growth_Score"])


def test_strict_missing_mode_blocks_missing_required_attrition_feature():
    repo = _seed_attrition_context(omit={"EngagementRecord.careerGrowthScore"})
    service = _service(repo)
    report = service.resolve_attrition(
        tenant_id="ORG-1", employee_id="E-1", strict_missing=True
    )
    assert report.status == ResolutionStatus.BLOCKED
    assert report.critical_missing_count == 1
    with pytest.raises(FeatureResolutionBlockedError):
        service.attrition_adapter.adapt(report)


def test_attrition_model_adapter_preserves_exact_order_and_boolean_to_yes_no():
    service = _service()
    report = service.resolve_attrition(tenant_id="ORG-1", employee_id="E-1")
    envelope = service.attrition_adapter.adapt(report)
    assert envelope.feature_order == EXPECTED_FEATURES
    assert envelope.values["Pay_Concern_Raised_Last_6M"] == "Yes"
    assert envelope.values["Monthly_Salary_PKR"] == 120000.0


def test_step8_does_not_invent_unapproved_months_since_promotion_derivation():
    repo = _seed_attrition_context(omit={"ExperienceProfile.monthsSinceLastPromotion"})
    # Even if career history might exist in a real graph, this ontology property is not
    # marked as an approved derived concept, so Step 8 must not guess a formula.
    report = _service(repo).resolve_attrition(tenant_id="ORG-1", employee_id="E-1")
    item = next(x for x in report.features if x.feature_name == "Months_Since_Last_Promotion")
    assert item.method == ResolutionMethod.MISSING
    assert item.derivation_rule is None


def test_performance_recalculation_contract_blocks_missing_required_but_allows_optional_missing():
    contract = DEFAULT_FEATURE_CONTRACTS.get("performance_recalculation")
    required_values = {
        "PerformanceEvidence.actualKpiValue": 95,
        "PerformanceEvidence.floorValue": 60,
        "PerformanceEvidence.targetValue": 90,
        "PerformanceEvidence.stretchValue": 110,
        "KPI.scoringDirection": "HigherIsBetter",
        "PerformanceEvidence.kpiWeightPercentage": 25,
    }
    report = DEFAULT_FEATURE_RESOLVER.resolve(
        contract,
        provider=MappingValueProvider(required_values),
        subject_id="E-1|KPI-1",
    )
    assert report.status == ResolutionStatus.DEGRADED
    assert report.optional_missing_count == 1
    assert report.critical_missing_count == 0

    required_values.pop("PerformanceEvidence.targetValue")
    blocked = DEFAULT_FEATURE_RESOLVER.resolve(
        contract,
        provider=MappingValueProvider(required_values),
        subject_id="E-1|KPI-1",
    )
    assert blocked.status == ResolutionStatus.BLOCKED
    assert blocked.critical_missing_count == 1


def test_missing_employee_returns_subject_not_found_without_guessing_values():
    service = _service(InMemoryGraphRepository())
    report = service.resolve_attrition(tenant_id="ORG-1", employee_id="NOPE")
    assert report.status == ResolutionStatus.SUBJECT_NOT_FOUND
    assert report.feature_count == 14
    assert report.missing_count == 14
    assert any("not found" in item.lower() for item in report.report_warnings)


def test_feature_resolution_health_exposes_graph_counts_and_contracts():
    service = _service()
    health = service.health("ORG-1")
    assert health["step"] == 8
    assert "attrition" in health["contracts"]
    assert "performance_recalculation" in health["contracts"]
    assert health["graph_node_count"] > 0
    assert health["graph_relationship_count"] > 0
