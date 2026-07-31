from __future__ import annotations

from successor_service.graph.state import SuccessorGraphState
from successor_service.utils.serialization import clean_payload

try:
    from langgraph.graph import END, START, StateGraph

    LANGGRAPH_AVAILABLE = True
except ImportError:
    LANGGRAPH_AVAILABLE = False


class _SequentialTestRunner:
    """Runs the same nodes when LangGraph is unavailable."""

    def __init__(self, owner: "SuccessorRecommendationGraph") -> None:
        self.owner = owner

    def invoke(
        self,
        state: SuccessorGraphState,
        config: dict | None = None,
    ) -> SuccessorGraphState:
        state = {**state, **self.owner.resolve_employee_node(state)}
        route = self.owner.route_after_resolution(state)
        if route == "clarification":
            return {**state, **self.owner.clarification_node(state)}

        for node in (
            self.owner.load_position_node,
            self.owner.build_candidate_pool_node,
            self.owner.evaluate_candidates_node,
            self.owner.rank_candidates_node,
            self.owner.reasoning_node,
            self.owner.build_response_node,
        ):
            state = {**state, **node(state)}
        return state


class SuccessorRecommendationGraph:
    """
    Agent 1 is this LangGraph orchestrator.

    It resolves the employee, calls data tools in a fixed order, builds
    deterministic features and scores, and ranks candidates. Agent 2 receives
    only the Top 5 compact scored evidence and generates four HR reasons.
    """

    def __init__(
        self,
        *,
        resolver_tool,
        position_tool,
        candidate_pool_tool,
        evidence_tool,
        feature_builder,
        scoring_engine,
        ranking_engine,
        reasoning_agent,
    ) -> None:
        self.resolver_tool = resolver_tool
        self.position_tool = position_tool
        self.candidate_pool_tool = candidate_pool_tool
        self.evidence_tool = evidence_tool
        self.feature_builder = feature_builder
        self.scoring_engine = scoring_engine
        self.ranking_engine = ranking_engine
        self.reasoning_agent = reasoning_agent
        self.runtime = (
            "langgraph" if LANGGRAPH_AVAILABLE else "sequential_test_fallback"
        )
        self.graph = self._build_graph()

    def _build_graph(self):
        if not LANGGRAPH_AVAILABLE:
            return _SequentialTestRunner(self)

        builder = StateGraph(SuccessorGraphState)
        builder.add_node("resolve_employee", self.resolve_employee_node)
        builder.add_node("clarification", self.clarification_node)
        builder.add_node("load_position", self.load_position_node)
        builder.add_node("build_candidate_pool", self.build_candidate_pool_node)
        builder.add_node("evaluate_candidates", self.evaluate_candidates_node)
        builder.add_node("rank_candidates", self.rank_candidates_node)
        builder.add_node("llm_reasoning", self.reasoning_node)
        builder.add_node("build_response", self.build_response_node)

        builder.add_edge(START, "resolve_employee")
        builder.add_conditional_edges(
            "resolve_employee",
            self.route_after_resolution,
            {
                "continue": "load_position",
                "clarification": "clarification",
            },
        )
        builder.add_edge("clarification", END)
        builder.add_edge("load_position", "build_candidate_pool")
        builder.add_edge("build_candidate_pool", "evaluate_candidates")
        builder.add_edge("evaluate_candidates", "rank_candidates")
        builder.add_edge("rank_candidates", "llm_reasoning")
        builder.add_edge("llm_reasoning", "build_response")
        builder.add_edge("build_response", END)

        # Stateless compile: no employee data is retained in an in-memory thread.
        return builder.compile()

    def resolve_employee_node(self, state: SuccessorGraphState) -> dict:
        resolution = self.resolver_tool.run(
            message=None,
            employee_id=state.get("employee_id"),
            employee_name=state.get("employee_name"),
        )
        update = {"resolution": resolution}
        if resolution["status"] == "resolved":
            update["target_profile"] = resolution["profile"]
            update["employee_id"] = resolution["profile"]["Employee_ID"]
        return update

    @staticmethod
    def route_after_resolution(state: SuccessorGraphState) -> str:
        return (
            "continue"
            if state["resolution"]["status"] == "resolved"
            else "clarification"
        )

    @staticmethod
    def clarification_node(state: SuccessorGraphState) -> dict:
        resolution = state["resolution"]
        return {
            "response": {
                "status": "needs_clarification",
                # The precise resolver outcome (not_found, ambiguous,
                # identifier_mismatch, invalid_reference) is preserved so
                # callers can tell "no such employee" apart from
                # "several employees matched".
                "resolution_status": resolution.get("status"),
                "message": resolution.get(
                    "message",
                    "The employee could not be uniquely resolved.",
                ),
                "matches": resolution.get("matches", []),
            }
        }

    def load_position_node(self, state: SuccessorGraphState) -> dict:
        profile = state["target_profile"]
        return {
            "position_context": self.position_tool.run(profile["Position_ID"])
        }

    def build_candidate_pool_node(self, state: SuccessorGraphState) -> dict:
        return {
            "candidate_pool": self.candidate_pool_tool.run(
                state["target_profile"]
            )
        }

    def evaluate_candidates_node(self, state: SuccessorGraphState) -> dict:
        evaluated: list[dict] = []
        skipped: list[dict] = []

        for candidate in state["candidate_pool"]:
            candidate_id = candidate["Employee_ID"]
            try:
                evidence = self.evidence_tool.run(candidate_id)
                features = self.feature_builder.build(
                    candidate_profile=candidate,
                    position_context=state["position_context"],
                    evidence=evidence,
                )
                score = self.scoring_engine.score(features)
                evaluated.append(
                    {
                        "Employee_ID": candidate_id,
                        "Employee_Name": candidate["Employee_Name"],
                        "Current_Position_Title": candidate["Position_Title"],
                        **features,
                        **score,
                    }
                )
            except Exception as error:
                skipped.append(
                    {
                        "employee_id": candidate_id,
                        "reason": str(error),
                    }
                )

        return {
            "evaluated_candidates": evaluated,
            "skipped_candidates": skipped,
        }

    def rank_candidates_node(self, state: SuccessorGraphState) -> dict:
        ranked = self.ranking_engine.rank(
            list(state["evaluated_candidates"])
        )
        return {
            "ranked_candidates": ranked,
            "selected_candidates": ranked[:5],
        }

    def reasoning_node(self, state: SuccessorGraphState) -> dict:
        reasons = self.reasoning_agent.explain_candidates(
            state["selected_candidates"]
        )
        return {"candidate_reasons": reasons}

    def build_response_node(self, state: SuccessorGraphState) -> dict:
        compact_candidates = []
        reasons = state.get("candidate_reasons", {})

        for candidate in state["selected_candidates"]:
            compact_candidates.append(
                {
                    "rank": candidate["rank"],
                    "employee_id": candidate["Employee_ID"],
                    "employee_name": candidate["Employee_Name"],
                    "current_position": candidate[
                        "Current_Position_Title"
                    ],
                    "final_score": candidate["final_score"],
                    "qualification_status": candidate[
                        "qualification_status"
                    ],
                    "readiness": candidate["readiness"],
                    "reasons": reasons.get(
                        candidate["Employee_ID"], []
                    ),
                }
            )

        return {
            "response": clean_payload(
                {"recommended_successors": compact_candidates}
            )
        }

    def invoke(
        self,
        *,
        employee_id: str | None = None,
        employee_name: str | None = None,
    ) -> dict:
        state: SuccessorGraphState = {
            "employee_id": employee_id,
            "employee_name": employee_name,
        }
        result = self.graph.invoke(state)

        response = result.get("response")
        if response is None:
            raise RuntimeError(
                "The successor graph finished without producing a response."
            )

        return clean_payload(response)
