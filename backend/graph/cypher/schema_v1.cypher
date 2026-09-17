CREATE CONSTRAINT kg_node_graph_id IF NOT EXISTS FOR (n:KGNode) REQUIRE n.kg_graph_id IS UNIQUE;
CREATE INDEX kg_node_tenant IF NOT EXISTS FOR (n:KGNode) ON (n.kg_tenant_id);
CREATE INDEX kg_node_entity_type IF NOT EXISTS FOR (n:KGNode) ON (n.kg_entity_type);
