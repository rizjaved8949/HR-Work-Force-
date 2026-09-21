"""Tenant-scoped, graph-native chatbot bridge.

It is additive and does not replace the existing `/chat` route.  The HR Insights
frontend can adopt this route in Step 2 while the legacy/default chatbot remains
untouched.
"""

from .router import create_tenant_graph_chat_router
from .service import TenantGraphChatService

__all__ = ["create_tenant_graph_chat_router", "TenantGraphChatService"]
