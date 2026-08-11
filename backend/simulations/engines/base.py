"""Base protocol for deterministic scenario engines."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..schemas import SimulationRequest, SimulationResponse


class BaseScenarioEngine(ABC):
    @abstractmethod
    def run(self, request: SimulationRequest) -> SimulationResponse:
        raise NotImplementedError
