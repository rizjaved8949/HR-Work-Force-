"""FastAPI routes for Step 11 existing HR application UI integration."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse

from service_refactor.runtime import Step9RuntimeManager

from .service import ExistingHRUIIntegrationService


STATIC_DIR = Path(__file__).resolve().parent / "static"


def _request_user(request: Request):
    return getattr(request.state, "user", None)


def create_ui_integration_router(
    runtime: Step9RuntimeManager,
    service: ExistingHRUIIntegrationService | None = None,
) -> APIRouter:
    integration = service or ExistingHRUIIntegrationService(runtime)
    router = APIRouter(prefix="/ui-integration", tags=["Step 11 UI Integration"])

    @router.get("/bootstrap")
    def bootstrap(request: Request):
        return integration.bootstrap(_request_user(request)).model_dump(mode="json")

    @router.get("/navigation")
    def navigation(request: Request):
        return {
            "tenant_id": runtime.config.tenant_id,
            "items": [item.model_dump(mode="json") for item in integration.navigation(_request_user(request))],
        }

    @router.get("/runtime")
    def runtime_status():
        return {
            "step": 11,
            "tenant_id": runtime.config.tenant_id,
            "graph_available": runtime.graph_available,
            "services": [item.model_dump(mode="json") for item in integration.runtime_services()],
        }

    @router.get("/api-contract")
    def api_contract():
        return {
            "step": 11,
            "ui_api_contract_preserved": runtime.status().ui_api_contract_preserved,
            "groups": [item.model_dump(mode="json") for item in integration.endpoint_groups()],
        }

    @router.get("/assets/hr-ui-client.js", include_in_schema=False)
    def client_sdk() -> FileResponse:
        return FileResponse(STATIC_DIR / "hr-ui-client.js", media_type="application/javascript")

    @router.get("", include_in_schema=False)
    def integration_console() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @router.get("/assets/styles.css", include_in_schema=False)
    def integration_css() -> FileResponse:
        return FileResponse(STATIC_DIR / "styles.css", media_type="text/css")

    @router.get("/assets/console.js", include_in_schema=False)
    def integration_js() -> FileResponse:
        return FileResponse(STATIC_DIR / "console.js", media_type="application/javascript")

    return router
