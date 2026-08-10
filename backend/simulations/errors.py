"""Scenario Simulation domain errors."""


class SimulationDataError(RuntimeError):
    """Raised when required simulation data is missing or inconsistent."""


class SimulationEmployeeNotFoundError(SimulationDataError):
    """Raised when an Employee_ID is not present in the current workforce master."""
