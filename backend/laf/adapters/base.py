"""Adapter base types shared by every local-generation backend.

ADR-010 rules all adapters follow:
- Availability is probed, never assumed: every adapter answers
  `available()` with a structured status, fast (sub-second) and
  side-effect free.
- Results carry an honest `method` label (e.g. "local_ollama",
  "fallback_template") so the UI can show the user how content was
  actually produced.
- Missing prerequisites raise AdapterUnavailable with a human-fixable
  message; nothing retries blindly against an absent service.
"""

from __future__ import annotations

from dataclasses import dataclass, field


class AdapterUnavailable(RuntimeError):
    """Raised when a generation adapter cannot do its job right now."""


@dataclass
class AdapterStatus:
    """Structured answer from `available()` probes."""

    name: str
    available: bool
    detail: str
    extra: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "available": self.available,
            "detail": self.detail,
            **({"extra": self.extra} if self.extra else {}),
        }
