"""HR Ontology v1 metadata package.

Step 2 integration mode: read-only and unmounted from the existing runtime.
"""

from .registry import DEFAULT_REGISTRY, OntologyRegistry, OntologyRegistryError
from .service import ONTOLOGY_SERVICE, OntologyService

__all__ = [
    "DEFAULT_REGISTRY",
    "ONTOLOGY_SERVICE",
    "OntologyRegistry",
    "OntologyRegistryError",
    "OntologyService",
]
