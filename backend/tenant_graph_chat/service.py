"""Read-only, tenant-scoped graph context and answer service.

The service never reads repository CSVs.  Every evidence record is fetched from
GraphRepository with the selected tenant_id.  The LLM is only allowed to explain
that bounded evidence; it does not query another data source.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any, Callable
from uuid import uuid4

from graph.repository import GraphRepository
from semantic.service import SemanticHRService

from .models import TenantGraphEvidence


_TOKEN_RE = re.compile(r"[A-Za-z0-9._-]+")

_TOPIC_ENTITY_TYPES: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("attrition", "leave", "turnover", "risk"), ("Employee", "AttritionRiskPrediction", "Employment")),
    (("performance", "kpi", "rating", "goal"), ("Employee", "PerformanceRecord", "PerformanceSummary", "KPI", "PerformanceEvidence")),
    (("attendance", "absent", "absence", "late"), ("Employee", "AttendanceRecord")),
    (("skill", "skills", "competency", "learning", "course", "training"), ("Employee", "EmployeeSkill", "Skill", "LearningRecord", "LearningCourse")),
    (("successor", "succession", "replacement"), ("Employee", "SuccessionReadiness", "SuccessorRecommendation", "Position")),
    (("headcount", "workforce", "budget", "vacancy"), ("HeadcountSnapshot", "DailyWorkforceActivity", "DepartmentBudget", "PositionBudget", "VacancyRecord", "Department")),
    (("scenario", "simulation", "what-if", "whatif"), ("ScenarioResult", "ScenarioAssumption", "Employee", "Position", "Department")),
    (("decision", "case", "rule"), ("DecisionCase", "DecisionRule", "Employee")),
    (("department", "business unit", "organization", "location", "position", "manager", "employee", "staff"), ("Organization", "BusinessUnit", "Department", "OrganizationalUnit", "WorkLocation", "Position", "Assignment", "Employee")),
)


def _default_model_factory():
    # Lazy imports keep the graph-context endpoint independently testable and
    # avoid initializing the chat stack until /tenant-graph/api/chat is used.
    from pydantic import SecretStr
    from resilient_model import ResilientChatOpenAI
    from settings import get_llm_settings

    llm = get_llm_settings()
    return ResilientChatOpenAI(
        model=llm.model,
        api_key=SecretStr(llm.api_key),
        base_url=llm.base_url,
        temperature=0,
        max_completion_tokens=min(llm.max_tokens, 1800),
        max_retries=llm.max_retries,
        timeout=llm.timeout_seconds,
        transient_max_attempts=llm.max_retries + 1,
        extra_body=llm.extra_body(),
        default_headers={
            "HTTP-Referer": "http://localhost:8000",
            "X-Title": "HR Workforce Tenant Graph Chat",
        },
    )


def _tokens(value: str) -> list[str]:
    return [
        token.casefold()
        for token in _TOKEN_RE.findall(value or "")
        if len(token) >= 2
    ]


def _node_label(node: Any) -> str:
    properties = dict(getattr(node, "properties", {}) or {})
    for key in (
        "name", "fullName", "employeeName", "employeeId", "organizationId",
        "departmentId", "positionId", "skillId", "kpiId", "courseId", "title",
    ):
        value = properties.get(key)
        if value not in (None, ""):
            return str(value)
    return str(getattr(node, "entity_type", "Node"))


def _node_text(node: Any) -> str:
    return (
        f"{getattr(node, 'entity_type', '')} {_node_label(node)} "
        + json.dumps(getattr(node, "properties", {}) or {}, ensure_ascii=False, default=str)
    ).casefold()


def _score(node: Any, query_tokens: list[str]) -> int:
    if not query_tokens:
        return 0
    text = _node_text(node)
    props = dict(getattr(node, "properties", {}) or {})
    score = sum(2 if token in text else 0 for token in query_tokens)
    employee_id = str(props.get("employeeId") or "").casefold()
    name = str(props.get("name") or props.get("employeeName") or "").casefold()
    for token in query_tokens:
        if employee_id and token == employee_id:
            score += 20
        if name and token in name:
            score += 5
    return score


class TenantGraphChatService:
    def __init__(
        self,
        *,
        repository: GraphRepository,
        model_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.repository = repository
        self.model_factory = model_factory or _default_model_factory
        self._model: Any | None = None

    def _entity_types_for(self, message: str) -> list[str]:
        lower = (message or "").casefold()
        result: list[str] = []
        for keywords, entity_types in _TOPIC_ENTITY_TYPES:
            if any(keyword in lower for keyword in keywords):
                for entity_type in entity_types:
                    if entity_type not in result:
                        result.append(entity_type)
        if not result:
            result = ["Employee", "Organization", "Department", "Assignment"]
        return result[:10]

    def _employee_context(self, tenant_id: str, message: str) -> tuple[str | None, dict[str, Any] | None]:
        # Employee populations are intentionally bounded below the repository's
        # 10k hard limit.  Current HR datasets are far smaller, and the match is
        # used only to obtain an exact business ID before semantic traversal.
        employees = self.repository.find_nodes(
            tenant_id=tenant_id,
            entity_type="Employee",
            limit=5000,
        )
        query_tokens = _tokens(message)
        ranked = sorted(
            ((node, _score(node, query_tokens)) for node in employees),
            key=lambda item: (-item[1], str(item[0].graph_id)),
        )
        if not ranked or ranked[0][1] <= 0:
            return None, None
        candidate = ranked[0][0]
        employee_id = str((candidate.properties or {}).get("employeeId") or "").strip()
        if not employee_id:
            return None, None
        semantic = SemanticHRService(self.repository)
        context = semantic.get_employee_context(
            tenant_id=tenant_id,
            employee_id=employee_id,
        )
        return employee_id, context.model_dump(mode="json") if context else None

    def build_context(
        self,
        *,
        tenant_id: str,
        message: str,
        max_nodes: int = 50,
    ) -> TenantGraphEvidence:
        max_nodes = max(10, min(int(max_nodes), 150))
        query_tokens = _tokens(message)
        entity_types = self._entity_types_for(message)
        per_type = max(20, min(500, max_nodes * 5))
        pool: dict[str, Any] = {}
        by_type: dict[str, list[Any]] = defaultdict(list)
        for entity_type in entity_types:
            for node in self.repository.find_nodes(
                tenant_id=tenant_id,
                entity_type=entity_type,
                limit=per_type,
            ):
                pool[str(node.graph_id)] = node
                by_type[entity_type].append(node)

        ranked = sorted(
            pool.values(),
            key=lambda node: (-_score(node, query_tokens), str(node.entity_type), str(node.graph_id)),
        )
        if query_tokens:
            positive = [node for node in ranked if _score(node, query_tokens) > 0]
            selected = positive[:max_nodes] if positive else ranked[: min(max_nodes, 30)]
        else:
            selected = ranked[:max_nodes]

        # Always keep a small balanced sample of requested entity types so broad
        # questions still have useful structure even if literal wording differs.
        selected_ids = {str(node.graph_id) for node in selected}
        for entity_type in entity_types:
            for node in by_type.get(entity_type, [])[:3]:
                if len(selected) >= max_nodes:
                    break
                if str(node.graph_id) not in selected_ids:
                    selected.append(node)
                    selected_ids.add(str(node.graph_id))

        graph_ids = [str(node.graph_id) for node in selected]
        between = getattr(self.repository, "find_relationships_between_nodes", None)
        if callable(between) and graph_ids:
            relationships = between(
                tenant_id=tenant_id,
                graph_ids=graph_ids,
                limit=min(max(max_nodes * 5, 100), 1000),
            )
        else:
            relationships = []

        matched_employee_id, employee_context = self._employee_context(
            tenant_id, message
        )

        nodes_payload = [
            {
                "graph_id": str(node.graph_id),
                "entity_type": str(node.entity_type),
                "label": _node_label(node),
                "properties": dict(node.properties or {}),
            }
            for node in selected
        ]
        relationships_payload = [
            {
                "relation_type": str(edge.relation_type),
                "source_graph_id": str(edge.source_graph_id),
                "source_entity_type": str(edge.source_entity_type),
                "target_graph_id": str(edge.target_graph_id),
                "target_entity_type": str(edge.target_entity_type),
                "properties": dict(edge.properties or {}),
            }
            for edge in relationships
        ]
        return TenantGraphEvidence(
            tenant_id=tenant_id,
            node_count_total=self.repository.count_nodes(tenant_id),
            relationship_count_total=self.repository.count_relationships(tenant_id),
            retrieved_node_count=len(nodes_payload),
            retrieved_relationship_count=len(relationships_payload),
            entity_types=sorted({item["entity_type"] for item in nodes_payload}),
            matched_employee_id=matched_employee_id,
            truncated=len(pool) > len(selected),
            nodes=nodes_payload,
            relationships=relationships_payload,
            employee_context=employee_context,
        )

    def _get_model(self):
        if self._model is None:
            self._model = self.model_factory()
        return self._model

    def answer(
        self,
        *,
        tenant_id: str,
        message: str,
        thread_id: str | None = None,
        max_nodes: int = 50,
    ) -> dict[str, Any]:
        evidence = self.build_context(
            tenant_id=tenant_id,
            message=message,
            max_nodes=max_nodes,
        )
        evidence_json = json.dumps(
            evidence.model_dump(mode="json"),
            ensure_ascii=False,
            default=str,
        )
        # Avoid an unbounded prompt if a tenant contains unusually large JSON
        # properties.  The structured response still exposes the full bounded
        # evidence object to the frontend.
        prompt_context = evidence_json[:50_000]
        messages = [
            {
                "role": "system",
                "content": (
                    "You are the HR Insights tenant-graph assistant. Answer only from "
                    "the supplied live Knowledge Graph evidence for the selected tenant. "
                    "Never use facts from another organization, prior tenant, CSV file, or "
                    "general assumptions. If the evidence is insufficient, say what is not "
                    "available. Prefer business names and IDs; do not expose internal graph_id "
                    "values unless the user explicitly asks for technical identifiers. If the "
                    "evidence says it is truncated, do not claim an exact total from the sample."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Selected tenant: {tenant_id}\n"
                    f"User question: {message}\n\n"
                    f"LIVE KNOWLEDGE GRAPH EVIDENCE:\n{prompt_context}"
                ),
            },
        ]
        reply_message = self._get_model().invoke(messages)
        content = getattr(reply_message, "content", reply_message)
        if isinstance(content, list):
            text_parts = []
            for item in content:
                if isinstance(item, dict):
                    text_parts.append(str(item.get("text") or item.get("content") or ""))
                else:
                    text_parts.append(str(item))
            content = "".join(text_parts)
        reply = str(content or "").strip()
        return {
            "thread_id": thread_id or str(uuid4()),
            "tenant_id": tenant_id,
            "reply": reply,
            "runtime_source": "canonical_knowledge_graph",
            "tenant_isolation": True,
            "evidence": evidence.model_dump(mode="json"),
        }
