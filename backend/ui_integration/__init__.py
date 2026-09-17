"""Step 11 existing HR application UI integration facade."""

from .router import create_ui_integration_router
from .service import ExistingHRUIIntegrationService

__all__ = ["ExistingHRUIIntegrationService", "create_ui_integration_router"]
