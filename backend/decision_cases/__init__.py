"""Isolated HR Decision Trigger Engine.

The module reads existing HR analytics outputs and creates decision-support
cases. It never changes employee, attrition, performance, headcount,
replacement, or simulation source data.
"""

from .service import DecisionCaseService

__all__ = ["DecisionCaseService"]
