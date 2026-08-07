"""Employee Performance feature package.

Core imports intentionally avoid the optional LangChain agent adapter so the
repository, scoring, services and API router remain independently testable.
"""

from performance.dashboard_service import PerformanceDashboardService
from performance.learning_service import PerformanceLearningService
from performance.repository import PerformanceRepository
from performance.router import create_performance_router
from performance.schemas import AnalyzePerformanceInput, PerformanceToolResult
from performance.service import PerformanceService

__all__ = [
    "AnalyzePerformanceInput",
    "PerformanceDashboardService",
    "PerformanceLearningService",
    "PerformanceRepository",
    "PerformanceService",
    "PerformanceToolResult",
    "create_performance_router",
]
