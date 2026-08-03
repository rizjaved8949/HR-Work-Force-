"""Attrition dashboard pipeline."""

from .people_at_risk_service import PeopleAtRiskService
from .router import create_attrition_dashboard_router

__all__ = [
    "PeopleAtRiskService",
    "create_attrition_dashboard_router",
]
