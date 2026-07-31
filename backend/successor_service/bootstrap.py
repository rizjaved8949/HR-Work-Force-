from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from successor_service.agents.recommendation_reasoning_agent import (
    RecommendationReasoningAgent,
)
from successor_service.config import get_settings, load_scoring_config
from successor_service.graph.successor_graph import (
    SuccessorRecommendationGraph,
)
from successor_service.repositories.csv_store import CSVDataStore
from successor_service.services.feature_builder import FeatureBuilder
from successor_service.services.ranking_engine import RankingEngine
from successor_service.services.scoring_engine import ScoringEngine
from successor_service.tools.candidate_pool_tool import CandidatePoolTool
from successor_service.tools.employee_evidence_tool import EmployeeEvidenceTool
from successor_service.tools.employee_resolver_tool import EmployeeResolverTool
from successor_service.tools.position_context_tool import PositionContextTool


def _normalize_data_dir(
    data_dir: str | Path | None,
) -> str | None:
    if data_dir is None:
        return None
    return str(Path(data_dir).expanduser().resolve())


@lru_cache(maxsize=4)
def _build_graph_cached(
    normalized_data_dir: str | None,
) -> SuccessorRecommendationGraph:
    settings = get_settings(normalized_data_dir)
    config = load_scoring_config(settings.scoring_config_path)
    store = CSVDataStore(settings.data_dir)

    reasoning_agent = RecommendationReasoningAgent(
        enabled=settings.llm_enabled,
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
        model=settings.openrouter_model,
        timeout_seconds=settings.openrouter_timeout_seconds,
        max_tokens=settings.openrouter_max_tokens,
        http_referer=settings.openrouter_http_referer,
        app_title=settings.openrouter_app_title,
    )

    return SuccessorRecommendationGraph(
        resolver_tool=EmployeeResolverTool(store),
        position_tool=PositionContextTool(store),
        candidate_pool_tool=CandidatePoolTool(store, config),
        evidence_tool=EmployeeEvidenceTool(store),
        feature_builder=FeatureBuilder(config),
        scoring_engine=ScoringEngine(config),
        ranking_engine=RankingEngine(config),
        reasoning_agent=reasoning_agent,
    )


def build_graph(
    data_dir: str | Path | None = None,
) -> SuccessorRecommendationGraph:
    """Build and cache the local successor graph for one data folder."""
    return _build_graph_cached(_normalize_data_dir(data_dir))


def build_agent(
    data_dir: str | Path | None = None,
) -> SuccessorRecommendationGraph:
    return build_graph(data_dir)
