from __future__ import annotations


class ScoringEngine:
    """Deterministic scoring; the reasoning agent never changes these scores."""

    def __init__(self, config: dict) -> None:
        self.weights = config["weights"]
        self.max_development_gaps = int(
            config["thresholds"]["maximum_development_gaps"]
        )

    def score(self, features: dict) -> dict:
        component_scores = {
            name: round(float(features[name]), 2)
            for name in self.weights
        }
        weighted_components = {
            name: round(component_scores[name] * float(weight), 2)
            for name, weight in self.weights.items()
        }
        final_score = round(sum(weighted_components.values()), 2)

        gap_count = int(features["hard_requirement_gap_count"])
        if gap_count == 0:
            status = "Qualified"
        elif gap_count <= self.max_development_gaps:
            status = "Development Candidate"
        else:
            status = "Not Qualified"

        return {
            "component_scores": component_scores,
            "weighted_components": weighted_components,
            "final_score": final_score,
            "qualification_status": status,
        }
