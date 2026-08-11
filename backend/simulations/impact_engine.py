"""Common deterministic impact helpers for scenario engines.

This module does not call an LLM and never mutates source data. It only
converts explicit numeric results into consistent risk/decision labels.
"""

from __future__ import annotations


class SimulationImpactEngine:
    @staticmethod
    def risk_band(score_pct: float) -> str:
        score = max(0.0, min(float(score_pct), 100.0))
        if score >= 85:
            return "critical"
        if score >= 70:
            return "high"
        if score >= 50:
            return "medium"
        return "low"

    @staticmethod
    def readiness_band(score_pct: float) -> str:
        score = max(0.0, min(float(score_pct), 100.0))
        if score >= 85:
            return "ready_now"
        if score >= 70:
            return "ready_with_minor_gaps"
        if score >= 55:
            return "development_required"
        return "not_ready"

    @staticmethod
    def decision_from_score(score_pct: float) -> str:
        score = max(0.0, min(float(score_pct), 100.0))
        if score >= 80:
            return "recommended"
        if score >= 65:
            return "recommended_with_conditions"
        if score >= 50:
            return "review_required"
        return "not_recommended"
