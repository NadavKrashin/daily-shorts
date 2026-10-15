"""Error taxonomy. The queue's retry policy is driven entirely by these classes."""
from __future__ import annotations


class WaitWhyError(Exception):
    error_class = "permanent"
    retryable = False


class TransientError(WaitWhyError):
    """Network blips, 429/5xx, provider busy. Retried with exponential backoff."""

    error_class = "transient"
    retryable = True

    def __init__(self, message: str, retry_after_s: float | None = None):
        super().__init__(message)
        self.retry_after_s = retry_after_s


class PermanentError(WaitWhyError):
    """Bad input, validation failure, unsupported operation. Never retried."""


class AuthError(PermanentError):
    """Expired/revoked credentials. Never retried; raises a HIGH alert."""

    error_class = "auth"


class PolicyError(PermanentError):
    """Platform/API policy restriction (e.g. unaudited client). Never retried, never bypassed."""

    error_class = "policy"


class BudgetExceeded(WaitWhyError):
    """Spending would exceed a cap. Work is paused (not failed) until a human approves."""

    error_class = "budget"

    def __init__(self, message: str, needed_usd: float = 0.0, remaining_usd: float = 0.0, scope: str = "monthly"):
        super().__init__(message)
        self.needed_usd = needed_usd
        self.remaining_usd = remaining_usd
        self.scope = scope


class ApprovalRequired(WaitWhyError):
    """A human decision is needed before continuing. Job is parked, not failed."""

    error_class = "approval"

    def __init__(self, message: str, approval_id: str | None = None):
        super().__init__(message)
        self.approval_id = approval_id


class AutomationPaused(WaitWhyError):
    error_class = "paused"
    retryable = True


class InvalidTransition(PermanentError):
    pass


class QualityGateFailed(PermanentError):
    error_class = "quality"
