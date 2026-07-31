from __future__ import annotations


class RankingEngine:
    def __init__(self, config: dict) -> None:
        self.priority = config["ranking_status_priority"]
        self.thresholds = config["thresholds"]

    def rank(self, candidates: list[dict]) -> list[dict]:
        ranked = sorted(
            candidates,
            key=lambda item: (
                int(self.priority.get(item["qualification_status"], 0)),
                float(item["final_score"]),
                float(item["skill_match_score"]),
                float(item["performance_score"]),
            ),
            reverse=True,
        )

        for index, item in enumerate(ranked, start=1):
            item["rank"] = index
            item["readiness"] = self._readiness(item)
        return ranked

    def _readiness(self, candidate: dict) -> str:
        status = candidate["qualification_status"]
        score = float(candidate["final_score"])
        gaps = int(candidate["hard_requirement_gap_count"])

        if status == "Qualified":
            if score >= float(self.thresholds["ready_now_score"]):
                return "Ready Now"
            if score >= float(self.thresholds["ready_soon_score"]):
                return "Ready in 3-6 Months"
            return "Ready in 6-12 Months"

        if status == "Development Candidate" and gaps <= 2:
            return "Ready in 6-12 Months"

        return "Not Ready"
