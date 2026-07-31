#Library
#recommendation_reasoning_agent_corrected.py
from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from successor_service.schemas.reasoning_models import TopFiveReasoning


logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """
You are an HR successor-recommendation reasoning agent.

Candidate scores and ranks were already calculated by a deterministic engine.
Never change ranking, scores, employee IDs, qualification status, or readiness.

For every supplied candidate, return exactly four short, specific reasons.
Use only supplied evidence. Never invent facts.

Language requirements:
1. Write all four reasons in professional English only.
2. Do not use Urdu, Roman Urdu, Hinglish, or mixed-language sentences.
3. Keep each reason clear, concise, and suitable for an HR dashboard.

Additional rules:
1. Return one object for every supplied employee_id.
2. Every employee_id must have exactly four reasons.
3. Never mention attrition probability or attrition labels.
4. Never expose internal column names, raw records, or calculations.
5. Never modify candidate ranking or scores.
6. Return only valid JSON matching the supplied schema.
""".strip()


class RecommendationReasoningAgent:
    """Agent 2: OpenRouter LLM reasoning after fixed scoring and ranking."""

    name = "openrouter_recommendation_reasoning_agent"

    def __init__(
        self,
        *,
        enabled: bool,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float,
        max_tokens: int,
        http_referer: str = "",
        app_title: str = "",
    ) -> None:
        self.enabled = enabled
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_tokens = max_tokens
        self.http_referer = http_referer
        self.app_title = app_title

    def explain_candidates(
        self,
        candidates: list[dict],
    ) -> dict[str, list[str]]:
        if not candidates:
            return {}

        compact_payload = [
            self._compact_candidate(item) for item in candidates
        ]

        # Without an explicit model in .env there is nothing to call, so the
        # deterministic reasons are used rather than guessing a model name.
        if self.enabled and self.api_key and self.model:
            try:
                llm_result = self._call_openrouter(compact_payload)
                return self._validate_and_complete(
                    llm_result,
                    candidates,
                )
            except Exception as error:
                logger.warning(
                    "OpenRouter reasoning failed; using deterministic "
                    "fallback reasons: %s",
                    error,
                )

        return {
            item["Employee_ID"]: self._fallback_reasons(item)
            for item in candidates
        }

    def health(self) -> dict[str, Any]:
        if not self.enabled:
            return {
                "enabled": False,
                "provider": "openrouter",
                "model": self.model,
                "configured": bool(self.api_key),
                "reachable": False,
            }

        if not self.api_key:
            return {
                "enabled": True,
                "provider": "openrouter",
                "model": self.model,
                "configured": False,
                "reachable": False,
                "message": "OPENROUTER_API_KEY is missing.",
            }

        try:
            response = httpx.get(
                f"{self.base_url}/models",
                headers=self._headers(),
                timeout=10.0,
            )
            response.raise_for_status()
            models = {
                str(item.get("id", ""))
                for item in response.json().get("data", [])
            }
            return {
                "enabled": True,
                "provider": "openrouter",
                "model": self.model,
                "configured": True,
                "reachable": True,
                "model_available": self.model in models,
            }
        except httpx.HTTPStatusError as error:
            return {
                "enabled": True,
                "provider": "openrouter",
                "model": self.model,
                "configured": True,
                "reachable": False,
                "http_status": error.response.status_code,
            }
        except Exception:
            return {
                "enabled": True,
                "provider": "openrouter",
                "model": self.model,
                "configured": True,
                "reachable": False,
            }

    def _call_openrouter(
        self,
        compact_payload: list[dict],
    ) -> TopFiveReasoning:
        if not self.api_key:
            raise RuntimeError("OPENROUTER_API_KEY is not configured.")

        schema = TopFiveReasoning.model_json_schema()
        prompt = (
            "Generate exactly four evidence-based reasons for each candidate."
            "\nCandidate evidence:\n"
            f"{json.dumps(compact_payload, ensure_ascii=False)}"
        )

        response = httpx.post(
            f"{self.base_url}/chat/completions",
            headers=self._headers(),
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0,
                "max_tokens": self.max_tokens,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "top_five_successor_reasoning",
                        "strict": True,
                        "schema": schema,
                    },
                },
                "provider": {
                    "require_parameters": True,
                },
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()

        body = response.json()
        content = body["choices"][0]["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            raise ValueError("OpenRouter returned empty reasoning content.")

        return TopFiveReasoning.model_validate_json(content)

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if self.http_referer:
            headers["HTTP-Referer"] = self.http_referer
        if self.app_title:
            headers["X-OpenRouter-Title"] = self.app_title
        return headers

    def _validate_and_complete(
        self,
        result: TopFiveReasoning,
        original_candidates: list[dict],
    ) -> dict[str, list[str]]:
        allowed = {
            item["Employee_ID"] for item in original_candidates
        }
        candidate_lookup = {
            item["Employee_ID"]: item for item in original_candidates
        }
        final: dict[str, list[str]] = {}

        for item in result.candidates:
            if item.employee_id not in allowed:
                continue

            reasons = [
                reason.strip()
                for reason in item.reasons
                if reason.strip()
            ]
            if len(reasons) == 4:
                final[item.employee_id] = reasons

        for employee_id in allowed:
            if employee_id not in final:
                final[employee_id] = self._fallback_reasons(
                    candidate_lookup[employee_id]
                )

        return final

    @staticmethod
    def _compact_candidate(candidate: dict) -> dict:
        return {
            "employee_id": candidate["Employee_ID"],
            "rank": candidate["rank"],
            "final_score": candidate["final_score"],
            "qualification_status": candidate[
                "qualification_status"
            ],
            "readiness": candidate["readiness"],
            "skill_match_score": candidate["skill_match_score"],
            "experience_score": candidate["experience_score"],
            "performance_score": candidate["performance_score"],
            "attendance_score": candidate["attendance_score"],
            "readiness_leadership_score": candidate[
                "readiness_leadership_score"
            ],
            "matched_skills": candidate.get(
                "matched_skills", []
            )[:5],
            "missing_skills": candidate.get(
                "missing_skills", []
            )[:5],
            "below_requirement_skills": candidate.get(
                "below_requirement_skills", []
            )[:5],
            "hard_requirement_gaps": candidate.get(
                "hard_requirement_gaps", []
            )[:5],
        }

    @staticmethod
    def _fallback_reasons(candidate: dict) -> list[str]:
        reasons: list[str] = []

        if candidate["skill_match_score"] >= 85:
            reasons.append(
                "The candidate has a strong match with the required "
                "position skills."
            )
        else:
            reasons.append(
                "The candidate has relevant core skills but requires "
                "further development."
            )

        if candidate["experience_score"] >= 85:
            reasons.append(
                "The candidate meets the relevant and total experience "
                "requirements."
            )
        else:
            reasons.append(
                "The candidate has a gap against the required experience "
                "threshold."
            )

        if candidate["performance_score"] >= 85:
            reasons.append(
                "The candidate has demonstrated strong recent job "
                "performance."
            )
        else:
            reasons.append(
                "The candidate requires improvement against the "
                "performance threshold."
            )

        gaps = candidate.get("hard_requirement_gaps", [])

        if not gaps:
            reasons.append(
                "The candidate meets all mandatory position requirements."
            )
        elif candidate["attendance_score"] >= 90:
            reasons.append(
                "The candidate has consistent attendance but still has "
                "some mandatory development gaps."
            )
        else:
            reasons.append(
                "The candidate has development gaps in mandatory "
                "position requirements."
            )

        return reasons[:4]