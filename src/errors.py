"""Error types whose messages are shown to the user as-is."""


class UserFacingError(Exception):
    """An error with a plain-language message and (ideally) a fix the user can apply."""


class TransitionError(UserFacingError):
    """Raised when a record cannot move to the requested workflow status."""
