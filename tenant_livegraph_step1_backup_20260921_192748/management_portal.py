"""Standalone management portal for the two technical HR management UIs.

Deploy this as its own Render service. It intentionally exposes only:

- /ontology-studio
- /organization-onboarding

The business HR frontend can remain on Vercel and link to this service.
Graph persistence is selected through GRAPH_BACKEND and is expected to be
``supabase`` for the no-separate-graph-server deployment.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
load_dotenv(ROOT / ".env", override=True)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from graph.factory import create_graph_repository_from_env, graph_backend_name
from multi_org.router import create_multi_org_router
from multi_org.service import MultiOrganizationOnboardingService
from ontology_studio.router import create_ontology_studio_router
from ontology_studio.service import OntologyStudioService


app = FastAPI(
    title="HR Ontology Management Portal",
    description="Standalone Ontology Studio + Multi-Organization Onboarding portal.",
    version="1.0.0-supabase-graph",
)

origins = [
    item.strip()
    for item in os.getenv("MANAGEMENT_ALLOWED_ORIGINS", "*").split(",")
    if item.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins or ["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["*"],
)

repository = create_graph_repository_from_env(verify_connectivity=False)

multi_org_service = MultiOrganizationOnboardingService(repository=repository)
default_tenant = os.getenv("STEP9_TENANT_ID", "ORGANIZATION-001")
multi_org_service.ensure_default_organization(
    tenant_id=default_tenant,
    name=os.getenv("STEP12_DEFAULT_ORGANIZATION_NAME", "Current Organization"),
    legacy_open_access=os.getenv("STEP12_DEFAULT_TENANT_OPEN_ACCESS", "true").strip().lower()
    in {"1", "true", "yes", "on"},
)

ontology_service = OntologyStudioService(
    graph_repository_factory=lambda: create_graph_repository_from_env(
        verify_connectivity=False
    )
)

app.include_router(create_ontology_studio_router(ontology_service))
app.include_router(create_multi_org_router(multi_org_service))


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/ontology-studio")


@app.get("/health")
def health():
    available = False
    error = None
    try:
        repository.verify_connectivity()
        available = True
    except Exception as exc:  # health should report rather than crash
        error = f"{type(exc).__name__}: {exc}"
    return {
        "status": "ok" if available else "degraded",
        "graph_backend": graph_backend_name(),
        "repository": type(repository).__name__,
        "graph_available": available,
        "error": error,
        "uis": ["/ontology-studio", "/organization-onboarding"],
    }
