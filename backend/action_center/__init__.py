"""Operational HR Action Center.

This package is additive. It does not modify the existing Attrition, Headcount,
Performance, Simulation, employee-search, or authentication modules.
"""

from .repository import ActionCenterRepository
from .service import ActionCenterService
from .router import create_action_center_router

__all__ = [
    "ActionCenterRepository",
    "ActionCenterService",
    "create_action_center_router",
]
