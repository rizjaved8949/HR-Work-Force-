"""Action Center domain errors."""


class ActionCenterError(RuntimeError):
    """Base Action Center error."""


class ActionCenterDataError(ActionCenterError):
    """Raised when Action Center CSV data is missing or invalid."""


class ActionCenterValidationError(ActionCenterError):
    """Raised when a requested HR action fails business validation."""


class ActionCenterNotFoundError(ActionCenterError):
    """Raised when a process, employee, position, or record is not found."""


class ActionCenterConflictError(ActionCenterError):
    """Raised when an action conflicts with current operational state."""


class ActionCenterAuthorizationError(ActionCenterError):
    """Raised when the current user may not perform Action Center writes."""
