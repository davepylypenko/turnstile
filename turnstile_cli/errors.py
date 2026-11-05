class TurnstileError(Exception):
    """User-facing failure; message is printed, exit code 2."""

class StaleStateError(TurnstileError):
    """state.json changed on disk since it was loaded."""

class LockHeld(TurnstileError):
    """Another turnstile process holds the state lock."""
