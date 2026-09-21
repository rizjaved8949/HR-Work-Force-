from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from graph.models import GraphNode
from tenant_graph_chat.router import create_tenant_graph_chat_router
from tenant_graph_chat.service import TenantGraphChatService


class FakeRepository:
    def __init__(self):
        self.nodes = {
            "ORGANIZATION-001": [
                GraphNode(
                    graph_id="org1",
                    tenant_id="ORGANIZATION-001",
                    entity_type="Organization",
                    ontology_version="1",
                    properties={"organizationId": "ORGANIZATION-001", "name": "Org One"},
                ),
                GraphNode(
                    graph_id="budget1",
                    tenant_id="ORGANIZATION-001",
                    entity_type="DepartmentBudget",
                    ontology_version="1",
                    properties={"departmentId": "D1", "budgetAmount": 100},
                ),
            ],
            "NEXACORE-HR-001": [
                GraphNode(
                    graph_id="org2",
                    tenant_id="NEXACORE-HR-001",
                    entity_type="Organization",
                    ontology_version="1",
                    properties={"organizationId": "NEXACORE-HR-001", "name": "NexaCore"},
                ),
                GraphNode(
                    graph_id="budget2",
                    tenant_id="NEXACORE-HR-001",
                    entity_type="DepartmentBudget",
                    ontology_version="1",
                    properties={"departmentId": "NX-D1", "budgetAmount": 999},
                ),
            ],
        }

    def find_nodes(self, *, tenant_id, entity_type=None, property_filters=None, limit=100):
        rows = list(self.nodes.get(tenant_id, []))
        if entity_type:
            rows = [row for row in rows if row.entity_type == entity_type]
        if property_filters:
            rows = [
                row for row in rows
                if all(row.properties.get(key) == value for key, value in property_filters.items())
            ]
        return rows[:limit]

    def find_relationships_between_nodes(self, *, tenant_id, graph_ids, limit=1200):
        return []

    def count_nodes(self, tenant_id=None):
        return len(self.nodes.get(tenant_id, [])) if tenant_id else sum(map(len, self.nodes.values()))

    def count_relationships(self, tenant_id=None):
        return 0

    def related_nodes(self, **kwargs):
        return []

    def get_node(self, graph_id, tenant_id):
        return next((n for n in self.nodes.get(tenant_id, []) if n.graph_id == graph_id), None)


class FakeModel:
    def invoke(self, messages):
        user = messages[-1]["content"]
        tenant = "NEXACORE-HR-001" if "NEXACORE-HR-001" in user else "ORGANIZATION-001"
        return SimpleNamespace(content=f"answer from {tenant}")


def test_graph_context_never_crosses_selected_tenant():
    service = TenantGraphChatService(repository=FakeRepository(), model_factory=lambda: FakeModel())
    evidence = service.build_context(
        tenant_id="NEXACORE-HR-001",
        message="show department budget",
        max_nodes=20,
    )
    assert evidence.tenant_id == "NEXACORE-HR-001"
    assert all(item["properties"].get("budgetAmount") != 100 for item in evidence.nodes)
    assert any(item["properties"].get("budgetAmount") == 999 for item in evidence.nodes)


def test_graph_chat_route_uses_selected_organization_header():
    service = TenantGraphChatService(repository=FakeRepository(), model_factory=lambda: FakeModel())
    app = FastAPI()
    app.include_router(create_tenant_graph_chat_router(service))
    client = TestClient(app)
    response = client.post(
        "/tenant-graph/api/chat",
        headers={"X-Organization-ID": "NEXACORE-HR-001"},
        json={"message": "show department budget"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["tenant_id"] == "NEXACORE-HR-001"
    assert payload["runtime_source"] == "canonical_knowledge_graph"
    assert payload["tenant_isolation"] is True
    assert "NEXACORE-HR-001" in payload["reply"]
