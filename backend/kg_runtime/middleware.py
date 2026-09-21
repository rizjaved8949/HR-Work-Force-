"""Non-breaking source proof headers for every backend response."""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response
from starlette.types import ASGIApp

from graph.factory import graph_backend_name

from .config import KGRuntimeConfig


class KGRuntimeSourceHeaderMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        self.config = KGRuntimeConfig.from_env()

    async def dispatch(self, request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        source = "knowledge_graph" if self.config.enabled else "legacy"
        response.headers["X-HR-Data-Source"] = source
        response.headers["X-HR-Graph-Backend"] = graph_backend_name()
        response.headers["X-HR-LLM-Graph-Only"] = (
            "true" if self.config.enabled and self.config.enforce_llm_graph_only else "false"
        )
        return response


def install_kg_runtime_source_headers(app) -> None:
    app.add_middleware(KGRuntimeSourceHeaderMiddleware)
