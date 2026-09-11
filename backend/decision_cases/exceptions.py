class DecisionCaseError(RuntimeError):
    """Base error for the isolated Decision Trigger Engine."""


class DecisionCaseStorageError(DecisionCaseError):
    """Raised when the case store cannot be reached or is not configured."""
