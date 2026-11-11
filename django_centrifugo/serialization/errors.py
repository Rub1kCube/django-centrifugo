from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ValidationIssue:
    """A validation issue independent of the model library."""

    loc: tuple[str | int, ...]
    """Path to the invalid value, when available."""

    message: str
    """Description supplied by the backend."""

    type: str
    """Backend-specific issue identifier."""

    params: dict[str, Any] = field(default_factory=dict)
    """Additional backend context; values need not be JSON serializable."""
