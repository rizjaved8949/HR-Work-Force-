"""Scenario Simulation domain errors."""


class SimulationDataError(RuntimeError):
    """Raised when required simulation data is missing or inconsistent."""


class SimulationEmployeeNotFoundError(SimulationDataError):
    """Raised when an Employee_ID is not present in the current workforce master."""


class SimulationPositionNotFoundError(SimulationDataError):
    """Raised when a Position_ID is not present in Position_Master.csv."""


class SimulationValidationError(ValueError):
    """Raised when a what-if request is structurally valid but not meaningful."""


class SimulationScenarioNotImplementedError(NotImplementedError):
    """Raised while a locked scenario exists in the catalog but its engine is pending."""
