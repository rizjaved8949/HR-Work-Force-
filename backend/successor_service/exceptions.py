class SuccessorServiceError(Exception):
    """Base service error."""


class RecordNotFoundError(SuccessorServiceError):
    """Requested employee, position, or evidence record was not found."""


class InvalidRequestError(SuccessorServiceError):
    """Request is valid JSON but cannot be processed."""
