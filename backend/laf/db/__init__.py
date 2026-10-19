"""SQLite access layer: WAL connection + migration runner (ADR-002)."""

from .connection import connect
from .migrations import MigrationError, current_version, ensure_schema

__all__ = ["connect", "ensure_schema", "current_version", "MigrationError"]
