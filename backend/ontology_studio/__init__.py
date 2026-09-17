"""Step 10 Ontology Studio management plane.

This package exposes a safe management/read layer for the active HR ontology,
source mappings, service coverage, graph health and review workflows.  Draft
reviews never mutate the active ontology or Step-3 mapping files directly.
"""

from .router import create_ontology_studio_router
from .service import OntologyStudioService

__all__ = ["OntologyStudioService", "create_ontology_studio_router"]
