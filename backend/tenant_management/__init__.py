"""Additive tenant-management APIs for live graph selection and merge uploads.

This module deliberately sits beside the existing Step-12 onboarding code.  It
adds convenience endpoints without changing any existing onboarding endpoint or
its default replace-snapshot semantics.
"""

from .router import create_tenant_management_router

__all__ = ["create_tenant_management_router"]
