"""Generate inspectable Step-4 graph schema artifacts from ontology."""

from __future__ import annotations

from .service import GRAPH_MODEL_SERVICE


def main() -> None:
    manifest, cypher = GRAPH_MODEL_SERVICE.write_generated_files()
    print(f"Graph manifest: {manifest}")
    print(f"Neo4j schema:   {cypher}")
    print(GRAPH_MODEL_SERVICE.summary())


if __name__ == "__main__":
    main()
