from __future__ import annotations

from django.db import connection

LOCK_TIMEOUT_MS = 2_000
STATEMENT_TIMEOUT_MS = 60_000


def set_chunk_timeouts(
    lock_timeout_ms: int = LOCK_TIMEOUT_MS,
    statement_timeout_ms: int = STATEMENT_TIMEOUT_MS,
) -> None:
    """Set per-transaction lock and statement timeouts for a deletion chunk."""
    if connection.vendor != "postgresql":
        return
    with connection.cursor() as cursor:
        cursor.execute(f"SET LOCAL lock_timeout = '{lock_timeout_ms}ms'")
        cursor.execute(f"SET LOCAL statement_timeout = '{statement_timeout_ms}ms'")


def analyze_tables(table_names: list[str]) -> None:
    """Run ANALYZE on the given tables. No-op on non-PostgreSQL backends."""
    if connection.vendor != "postgresql":
        return
    with connection.cursor() as cursor:
        for table in table_names:
            cursor.execute(f"ANALYZE {table}")  # noqa: S608 — table names are internal constants
