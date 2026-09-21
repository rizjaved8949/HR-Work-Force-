from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from graph.models import GraphNode, GraphRelationship
from ontology_studio.router import create_ontology_studio_router
from ontology_studio.service import OntologyStudioService
from ontology_studio.store import StudioReviewStore


TENANT = "NEXACORE-HR-001"


def node(graph_id: str, entity_type: str, **props) -> GraphNode:
    return GraphNode(
        graph_id=graph_id,
        tenant_id=TENANT,
        entity_type=entity_type,
        ontology_version="1.0.2-draft",
        properties=props,
    )


class LiveFakeRepository:
    def __init__(self):
        self.nodes = {
            "employee:e1": node("employee:e1", "Employee", employeeId="E1", name="Ali"),
            "employee:e2": node("employee:e2", "Employee", employeeId="E2", name="Sara"),
            "department:d1": node("department:d1", "Department", departmentId="D1", name="Engineering"),
        }
        self.edges = [
            GraphRelationship(
                graph_id="edge:works",
                tenant_id=TENANT,
                relation_type="WORKS_FOR",
                source_graph_id="employee:e1",
                source_entity_type="Employee",
                target_graph_id="department:d1",
                target_entity_type="Department",
                ontology_version="1.0.2-draft",
            ),
            GraphRelationship(
                graph_id="edge:reports",
                tenant_id=TENANT,
                relation_type="REPORTS_TO",
                source_graph_id="employee:e1",
                source_entity_type="Employee",
                target_graph_id="employee:e2",
                target_entity_type="Employee",
                ontology_version="1.0.2-draft",
            ),
        ]

    def verify_connectivity(self):
        return None

    def close(self):
        return None

    def count_nodes(self, tenant_id=None):
        return len(self.nodes) if tenant_id == TENANT else 0

    def count_relationships(self, tenant_id=None):
        return len(self.edges) if tenant_id == TENANT else 0

    def find_nodes(self, *, tenant_id, entity_type=None, property_filters=None, limit=100):
        if tenant_id != TENANT:
            return []
        items = list(self.nodes.values())
        if entity_type:
            items = [item for item in items if item.entity_type == entity_type]
        return items[:limit]

    def get_node(self, graph_id, tenant_id):
        if tenant_id != TENANT:
            return None
        return self.nodes.get(graph_id)

    def find_nodes_by_ids(self, *, tenant_id, graph_ids, limit=500):
        if tenant_id != TENANT:
            return []
        return [self.nodes[item] for item in graph_ids if item in self.nodes][:limit]

    def find_relationships(self, *, tenant_id, source_graph_id=None, target_graph_id=None, relation_type=None, limit=100):
        if tenant_id != TENANT:
            return []
        items = list(self.edges)
        if source_graph_id:
            items = [item for item in items if item.source_graph_id == source_graph_id]
        if target_graph_id:
            items = [item for item in items if item.target_graph_id == target_graph_id]
        if relation_type:
            items = [item for item in items if item.relation_type == relation_type]
        return items[:limit]

    def find_relationships_between_nodes(self, *, tenant_id, graph_ids, limit=1200):
        ids = set(graph_ids)
        return [
            item for item in self.edges
            if tenant_id == TENANT and item.source_graph_id in ids and item.target_graph_id in ids
        ][:limit]


def make_service(tmp_path: Path):
    return OntologyStudioService(
        store=StudioReviewStore(tmp_path / "reviews.json"),
        graph_repository_factory=LiveFakeRepository,
    )


def test_mapping_review_options_are_controlled_select_values(tmp_path):
    payload = make_service(tmp_path).mapping_review_options()
    paths = {item["value"] for item in payload["ontology_paths"]}
    assert "Employee.employeeId" in paths
    assert "BusinessUnit.name" in paths
    assert "direct_property" in payload["dispositions"]
    assert "relationship_reference" in payload["dispositions"]


def test_live_graph_returns_actual_tenant_nodes_and_edges(tmp_path):
    payload = make_service(tmp_path).live_graph(TENANT, limit=20)
    assert payload["mode"] == "live"
    assert payload["node_count_total"] == 3
    assert payload["relationship_count_total"] == 2
    assert {item["entity_type"] for item in payload["nodes"]} == {"Employee", "Department"}
    assert {item["relation_type"] for item in payload["edges"]} == {"WORKS_FOR", "REPORTS_TO"}
    ali = next(item for item in payload["nodes"] if item["graph_id"] == "employee:e1")
    assert ali["label"] == "Ali"


def test_live_node_click_returns_one_hop_neighborhood_and_details(tmp_path):
    payload = make_service(tmp_path).live_node_neighborhood(TENANT, "employee:e1", limit=20)
    assert payload["center_graph_id"] == "employee:e1"
    assert payload["node_detail"]["properties"]["employeeId"] == "E1"
    assert payload["outgoing_count"] == 2
    assert payload["incoming_count"] == 0
    assert payload["neighbor_count"] == 2
    assert {item["graph_id"] for item in payload["nodes"]} == {
        "employee:e1", "employee:e2", "department:d1"
    }


def test_router_exposes_live_graph_and_mapping_option_endpoints(tmp_path):
    app = FastAPI()
    app.include_router(create_ontology_studio_router(make_service(tmp_path)))
    client = TestClient(app)
    live = client.get(f"/ontology-studio/api/live-graph?tenant_id={TENANT}")
    assert live.status_code == 200
    detail = client.get(f"/ontology-studio/api/live-graph/nodes/employee:e1?tenant_id={TENANT}")
    assert detail.status_code == 200
    assert detail.json()["neighbor_count"] == 2
    options = client.get("/ontology-studio/api/mapping-review-options")
    assert options.status_code == 200
    assert options.json()["ontology_paths"]


def test_ui_has_live_graph_mode_zoom_and_mapping_selectors():
    html = Path("backend/ontology_studio/static/index.html").read_text()
    js = Path("backend/ontology_studio/static/app.js").read_text()
    assert 'data-mode="live"' in html
    assert 'id="zoom-in"' in html and 'id="zoom-out"' in html
    assert '<select id="review-path"' in html
    assert '<select id="review-disposition"' in html
    assert "/ontology-studio/api/live-graph" in js
    assert "loadLiveNode" in js
    assert "mapping-review-options" in js
