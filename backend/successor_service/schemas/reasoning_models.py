from __future__ import annotations

from pydantic import BaseModel, Field


class CandidateReasoning(BaseModel):
    employee_id: str
    reasons: list[str] = Field(min_length=4, max_length=4)


class TopFiveReasoning(BaseModel):
    candidates: list[CandidateReasoning] = Field(min_length=1, max_length=5)
