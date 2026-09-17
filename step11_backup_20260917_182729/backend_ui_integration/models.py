"""Typed models for Step 11 existing HR application UI integration."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


NavAudience = Literal["all", "admin"]


class UINavItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    route_key: str
    audience: NavAudience = "all"
    enabled: bool = True
    backend_surface: str | None = None
    description: str | None = None


class UIEndpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    method: Literal["GET", "POST", "PATCH"]
    path: str
    module: str
    purpose: str
    timeout_seconds: int = 30
    streaming: bool = False


class UIEndpointGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    module: str
    label: str
    endpoints: list[UIEndpoint] = Field(default_factory=list)


class UIUserContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    authenticated: bool
    user_id: str | None = None
    full_name: str | None = None
    email: str | None = None
    role: str | None = None
    is_admin: bool = False


class UIServiceRuntime(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service: str
    state: str
    active_source: str
    graph_capable: bool
    fallback_enabled: bool
    notes: list[str] = Field(default_factory=list)


class UIIntegrationBootstrap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step: int = 11
    name: str = "Existing HR Application UI Integration"
    app_name: str
    tenant_id: str
    auth_enabled: bool
    graph_available: bool
    ui_api_contract_preserved: bool
    user: UIUserContext
    navigation: list[UINavItem]
    endpoint_groups: list[UIEndpointGroup]
    runtime_services: list[UIServiceRuntime]
    feature_flags: dict[str, bool]
    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
