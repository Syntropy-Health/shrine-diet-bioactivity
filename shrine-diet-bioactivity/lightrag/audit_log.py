"""
Append-only audit log for the shrine-diet-bioactivity MCP server.

One row per tool invocation (MCP tool on the TS side — or, during Phase
A2, per ``POST /query`` on ``scoped_server.py``). Rows never carry raw
query text; queries are SHA-256 hashed. The table is the source of
truth for:

- **Traceability** — every action a tenant took, by time
- **Billing** — per-tenant invocation count + token usage
- **Debug** — error-class roll-up per tenant

Writes are defensive: an audit failure must never break a query. All
errors inside ``emit_*`` are swallowed after logging to stderr.

Table schema::

    CREATE TABLE mcp_audit (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        ts            TEXT NOT NULL,        -- ISO 8601 UTC
        tenant_id     TEXT,                  -- NULL = shared / anonymous
        tool          TEXT NOT NULL,
        query_hash    TEXT,
        scope_filter  TEXT NOT NULL,         -- JSON array
        latency_ms    INTEGER NOT NULL,
        result_count  INTEGER,
        token_usage   INTEGER,
        status        TEXT NOT NULL,         -- 'ok' | 'error' | 'invalid_tenant'
        error_class   TEXT
    )
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

logger = logging.getLogger(__name__)

DEFAULT_AUDIT_DB_PATH = Path(__file__).parent / "audit" / "mcp_audit.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS mcp_audit (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            TEXT NOT NULL,
    tenant_id     TEXT,
    tool          TEXT NOT NULL,
    query_hash    TEXT,
    scope_filter  TEXT NOT NULL,
    latency_ms    INTEGER NOT NULL,
    result_count  INTEGER,
    token_usage   INTEGER,
    status        TEXT NOT NULL,
    error_class   TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_tenant_ts
    ON mcp_audit(tenant_id, ts);

CREATE INDEX IF NOT EXISTS idx_audit_ts
    ON mcp_audit(ts);
"""


@dataclass
class AuditRow:
    """A single audit record assembled during a tool call."""

    tool: str
    scope_filter: list[str]
    tenant_id: str | None = None
    query_hash: str | None = None
    result_count: int | None = None
    token_usage: int | None = None
    status: str = "ok"
    error_class: str | None = None
    _started_at: float = field(default_factory=time.monotonic)

    def latency_ms(self) -> int:
        return int((time.monotonic() - self._started_at) * 1000)


class AuditLog:
    """Thread-safe-enough SQLite audit emitter.

    SQLite handles concurrent writers via file-level locks — acceptable
    for the MCP's expected throughput (<< 100 writes/sec). Upgrade to a
    queue + background flush thread if this becomes hot.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = Path(db_path) if db_path else DEFAULT_AUDIT_DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.executescript(_SCHEMA)
        except sqlite3.Error as e:
            # Don't raise — audit must never block the server from booting.
            print(
                f"[audit-log] WARN: failed to ensure schema at {self._db_path}: {e}",
                file=sys.stderr,
            )

    def emit(self, row: AuditRow) -> None:
        """Append one row. Never raises — on failure, logs to stderr."""
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO mcp_audit (
                        ts, tenant_id, tool, query_hash, scope_filter,
                        latency_ms, result_count, token_usage,
                        status, error_class
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        datetime.now(timezone.utc).isoformat(),
                        row.tenant_id,
                        row.tool,
                        row.query_hash,
                        json.dumps(row.scope_filter),
                        row.latency_ms(),
                        row.result_count,
                        row.token_usage,
                        row.status,
                        row.error_class,
                    ),
                )
        except Exception as e:  # broad-except: audit must be fire-and-forget
            print(
                f"[audit-log] WARN: failed to emit row ({row.tool}, {row.status}): {e}",
                file=sys.stderr,
            )

    @contextmanager
    def record(
        self,
        tool: str,
        scope_filter: list[str],
        tenant_id: str | None = None,
        query_body: object | None = None,
    ) -> Iterator[AuditRow]:
        """Context manager — yields a mutable AuditRow; emits on exit.

        Usage::

            with audit.record('semantic-search', scope, tenant, body) as row:
                result = await rag.aquery(...)
                row.result_count = len(result)
                row.token_usage = result.meta.tokens
        """
        row = AuditRow(
            tool=tool,
            scope_filter=list(scope_filter),
            tenant_id=tenant_id,
            query_hash=hash_query(query_body) if query_body is not None else None,
        )
        try:
            yield row
        except Exception as e:
            row.status = "error"
            row.error_class = type(e).__name__
            raise
        finally:
            self.emit(row)


def hash_query(body: object) -> str:
    """SHA-256 hex digest of the JSON-normalised query body.

    Keys are sorted so semantically-equal queries hash identically.
    Non-serialisable values are str()'d — not bullet-proof but enough
    for audit correlation.
    """
    try:
        payload = json.dumps(body, sort_keys=True, default=str)
    except (TypeError, ValueError):
        payload = str(body)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# Module-level convenience singleton for simple call sites.
_default: AuditLog | None = None


def default_audit_log() -> AuditLog:
    """Lazy-initialised singleton at ``DEFAULT_AUDIT_DB_PATH``."""
    global _default
    if _default is None:
        _default = AuditLog()
    return _default
