from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from graph.models import GraphNode, GraphRelationship
from graph.supabase_repository import SupabaseGraphRepository


@dataclass
class FakeResponse:
    data: list
    count: int | None = None


class FakeQuery:
    def __init__(self, client, table):
        self.client = client
        self.table = table
        self.mode = "select"
        self.payload = None
        self.filters = []
        self.json_contains = []
        self.ids = []
        self.max_rows = None
        self.want_count = None
        self.on_conflict = None

    def select(self, *args, **kwargs):
        self.mode = "select"
        self.want_count = kwargs.get("count")
        return self

    def upsert(self, payload, on_conflict=None):
        self.mode = "upsert"
        self.payload = payload if isinstance(payload, list) else [payload]
        self.on_conflict = on_conflict
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def contains(self, column, value):
        self.json_contains.append((column, value))
        return self

    def in_(self, column, values):
        self.ids.append((column, set(values)))
        return self

    def order(self, *args, **kwargs):
        return self

    def limit(self, value):
        self.max_rows = int(value)
        return self

    def execute(self):
        store = self.client.tables.setdefault(self.table, [])
        if self.mode == "upsert":
            for item in self.payload:
                key = (item["tenant_id"], item["graph_id"])
                for index, current in enumerate(store):
                    if (current["tenant_id"], current["graph_id"]) == key:
                        store[index] = dict(item)
                        break
                else:
                    store.append(dict(item))
            return FakeResponse(list(self.payload))

        rows = list(store)
        for col, value in self.filters:
            rows = [row for row in rows if row.get(col) == value]
        for col, value in self.json_contains:
            rows = [
                row for row in rows
                if all((row.get(col) or {}).get(k) == v for k, v in value.items())
            ]
        for col, values in self.ids:
            rows = [row for row in rows if row.get(col) in values]
        count = len(rows) if self.want_count == "exact" else None
        if self.max_rows is not None:
            rows = rows[: self.max_rows]
        return FakeResponse(rows, count=count)


class FakeSupabase:
    def __init__(self):
        self.tables = {"kg_nodes": [], "kg_relationships": []}

    def table(self, name):
        return FakeQuery(self, name)


def employee(graph_id: str, tenant: str, employee_id: str, name: str) -> GraphNode:
    return GraphNode(
        graph_id=graph_id,
        tenant_id=tenant,
        entity_type="Employee",
        ontology_version="1.0.2-draft",
        properties={"employeeId": employee_id, "name": name},
    )


def test_supabase_graph_repository_is_tenant_scoped_and_traversable():
    client = FakeSupabase()
    repo = SupabaseGraphRepository(client=client)
    repo.verify_connectivity()

    a = employee("node-a", "ORG-A", "E-1", "Ali")
    b = employee("node-b", "ORG-A", "E-2", "Sara")
    same_id_other_tenant = employee("node-a", "ORG-B", "E-1", "Other Ali")
    assert repo.upsert_nodes_bulk([a, b, same_id_other_tenant]) == 3

    edge = GraphRelationship(
        graph_id="edge-1",
        tenant_id="ORG-A",
        relation_type="REPORTS_TO",
        source_graph_id="node-a",
        source_entity_type="Employee",
        target_graph_id="node-b",
        target_entity_type="Employee",
        ontology_version="1.0.2-draft",
    )
    repo.upsert_relationship(edge)

    assert repo.count_nodes("ORG-A") == 2
    assert repo.count_nodes("ORG-B") == 1
    assert repo.count_relationships("ORG-A") == 1
    assert repo.find_nodes(
        tenant_id="ORG-A", entity_type="Employee", property_filters={"employeeId": "E-1"}
    )[0].properties["name"] == "Ali"
    related = repo.related_nodes(
        tenant_id="ORG-A", graph_id="node-a", relation_type="REPORTS_TO", direction="out"
    )
    assert [node.properties["name"] for node in related] == ["Sara"]


def test_bulk_upsert_is_idempotent():
    client = FakeSupabase()
    repo = SupabaseGraphRepository(client=client)
    node = employee("node-a", "ORG-A", "E-1", "Ali")
    repo.upsert_nodes_bulk([node])
    repo.upsert_nodes_bulk([node.model_copy(update={"properties": {"employeeId": "E-1", "name": "Ali Updated"}})])
    assert repo.count_nodes("ORG-A") == 1
    assert repo.get_node("node-a", "ORG-A").properties["name"] == "Ali Updated"


def test_supabase_graph_schema_has_tenant_keys_fks_indexes_and_rls():
    sql = Path("backend/graph/sql/supabase_graph_schema.sql").read_text()
    assert "create table if not exists public.kg_nodes" in sql
    assert "create table if not exists public.kg_relationships" in sql
    assert "primary key (tenant_id, graph_id)" in sql
    assert "foreign key (tenant_id, source_graph_id)" in sql
    assert "foreign key (tenant_id, target_graph_id)" in sql
    assert "enable row level security" in sql
    assert "properties jsonb" in sql


def test_ontology_studio_graph_has_three_relationship_families_and_labels():
    js = Path("backend/ontology_studio/static/app.js").read_text()
    css = Path("backend/ontology_studio/static/styles.css").read_text()
    assert "edge-structure" in js and "edge-talent" in js and "edge-planning" in js
    assert "Relationship colours" in js
    assert "edge-label" in js
    assert "marker-end" in js
    assert "#52d6ff" in css
    assert "#a78bfa" in css
    assert "#f6c85f" in css


def test_standalone_management_portal_exposes_only_requested_management_uis():
    source = Path("management_portal.py").read_text()
    assert "create_ontology_studio_router" in source
    assert "create_multi_org_router" in source
    assert "create_ui_integration_router" not in source
    html = Path("backend/multi_org/static/index.html").read_text()
    assert "HR UI Integration" not in html
    assert "Ontology Studio" in html
