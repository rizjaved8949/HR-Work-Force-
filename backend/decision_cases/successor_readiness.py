from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from typing import Any

from successor_service.agents.recommendation_reasoning_agent import (
    RecommendationReasoningAgent,
)
from successor_service.config import get_settings, load_scoring_config
from successor_service.graph.successor_graph import SuccessorRecommendationGraph
from successor_service.repositories.csv_store import CSVDataStore
from successor_service.services.feature_builder import FeatureBuilder
from successor_service.services.ranking_engine import RankingEngine
from successor_service.services.scoring_engine import ScoringEngine
from successor_service.tools.candidate_pool_tool import CandidatePoolTool
from successor_service.tools.employee_evidence_tool import EmployeeEvidenceTool
from successor_service.tools.employee_resolver_tool import EmployeeResolverTool
from successor_service.tools.position_context_tool import PositionContextTool

from .data_repository import DecisionCaseDataRepository


class DeterministicSuccessorReadiness:
    """Reuse the existing successor scoring/ranking logic without any LLM call.

    The graph is rebuilt at the beginning of each Decision Trigger evaluation so
    updated CSV files are picked up without restarting FastAPI. In Supabase mode,
    the repository materializes the same successor input tables to a temporary
    directory and this class runs the unchanged scoring/ranking components on them.
    """

    def __init__(self, repository: DecisionCaseDataRepository) -> None:
        self.repository = repository
        self.graph: SuccessorRecommendationGraph | None = None
        self._stack: ExitStack | None = None

    @staticmethod
    def _build_uncached(data_dir: Path) -> SuccessorRecommendationGraph:
        settings = get_settings(data_dir)
        config = load_scoring_config(settings.scoring_config_path)
        store = CSVDataStore(settings.data_dir)

        # Case creation must remain deterministic. We intentionally disable the
        # successor reasoning LLM while reusing the exact candidate, feature,
        # scoring, readiness and ranking components used by the existing module.
        reasoning_agent = RecommendationReasoningAgent(
            enabled=False,
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

    def refresh(self) -> None:
        """Rebuild from the latest configured data source for one evaluation run."""

        if self._stack is not None:
            self._stack.close()

        self._stack = ExitStack()
        data_dir = self._stack.enter_context(self.repository.successor_data_dir())
        self.graph = self._build_uncached(data_dir)

    def close(self) -> None:
        if self._stack is not None:
            self._stack.close()
            self._stack = None
        self.graph = None

    def evaluate(self, employee_id: str) -> dict[str, Any]:
        if self.graph is None:
            self.refresh()
        assert self.graph is not None

        state: dict[str, Any] = {
            "employee_id": employee_id,
            "employee_name": None,
        }
        state.update(self.graph.resolve_employee_node(state))

        if self.graph.route_after_resolution(state) != "continue":
            return {
                "status": "unavailable",
                "has_ready_now": False,
                "top_candidate": None,
                "candidate_count": 0,
                "message": state.get("resolution", {}).get(
                    "message", "The employee could not be resolved."
                ),
            }

        for node in (
            self.graph.load_position_node,
            self.graph.build_candidate_pool_node,
            self.graph.evaluate_candidates_node,
            self.graph.rank_candidates_node,
        ):
            state.update(node(state))

        ranked = list(state.get("ranked_candidates") or [])
        ready_now = next(
            (candidate for candidate in ranked if candidate.get("readiness") == "Ready Now"),
            None,
        )
        top = ranked[0] if ranked else None

        compact_top = None
        if top:
            compact_top = {
                "employee_id": top.get("Employee_ID"),
                "employee_name": top.get("Employee_Name"),
                "current_position": top.get("Current_Position_Title"),
                "final_score": top.get("final_score"),
                "qualification_status": top.get("qualification_status"),
                "readiness": top.get("readiness"),
            }

        return {
            "status": "success",
            "has_ready_now": ready_now is not None,
            "top_candidate": compact_top,
            "candidate_count": len(ranked),
        }
