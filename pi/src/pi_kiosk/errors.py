class UserFacingError(RuntimeError):
    """Raised for recoverable problems that should be shown without a traceback."""


class DesktopSessionUnavailable(UserFacingError):
    """There is no graphical session to start something in right now (SSH, Xorg, ...)."""
