from __future__ import annotations

from django.db import connection, transaction

DEFAULT_CHUNK_SIZE = 5_000


def delete_in_chunks(
    *,
    table: str,
    pipeline_run_id: int,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    join_table: str | None = None,
    join_fk: str | None = None,
) -> int:
    """Delete rows owned by pipeline_run_id in batches.

    For direct ownership (join_table=None): filters table.pipeline_run_id = pipeline_run_id.
    For indirect children: joins through join_table on child.join_fk = join_table.id,
    then filters join_table.pipeline_run_id = pipeline_run_id.

    Each chunk runs in its own transaction with per-chunk lock and statement timeouts
    on PostgreSQL. Non-PostgreSQL backends (SQLite) use a simple subquery DELETE.

    Returns total rows deleted.
    """
    if connection.vendor == "postgresql":
        return _delete_postgresql(
            table=table,
            pipeline_run_id=pipeline_run_id,
            chunk_size=chunk_size,
            join_table=join_table,
            join_fk=join_fk,
        )
    return _delete_fallback(
        table=table,
        pipeline_run_id=pipeline_run_id,
        chunk_size=chunk_size,
        join_table=join_table,
        join_fk=join_fk,
    )


def _delete_postgresql(
    *,
    table: str,
    pipeline_run_id: int,
    chunk_size: int,
    join_table: str | None,
    join_fk: str | None,
) -> int:
    from apps.imports.services.deletion.postgres import set_chunk_timeouts

    total = 0
    while True:
        with transaction.atomic():
            set_chunk_timeouts()
            with connection.cursor() as cursor:
                if join_table is None:
                    cursor.execute(
                        f"""
                        WITH victim AS (
                            SELECT id
                            FROM {table}
                            WHERE pipeline_run_id = %s
                            ORDER BY id
                            LIMIT %s
                        )
                        DELETE FROM {table}
                        USING victim
                        WHERE {table}.id = victim.id
                        """,
                        [pipeline_run_id, chunk_size],
                    )
                else:
                    cursor.execute(
                        f"""
                        WITH victim AS (
                            SELECT child.id
                            FROM {table} child
                            JOIN {join_table} parent ON parent.id = child.{join_fk}
                            WHERE parent.pipeline_run_id = %s
                            ORDER BY child.id
                            LIMIT %s
                        )
                        DELETE FROM {table}
                        USING victim
                        WHERE {table}.id = victim.id
                        """,
                        [pipeline_run_id, chunk_size],
                    )
                deleted = cursor.rowcount if cursor.rowcount != -1 else 0

        total += deleted
        if deleted < chunk_size:
            break

    return total


def _delete_fallback(
    *,
    table: str,
    pipeline_run_id: int,
    chunk_size: int,
    join_table: str | None,
    join_fk: str | None,
) -> int:
    """Subquery-based DELETE for non-PostgreSQL backends (used in tests)."""
    total = 0
    while True:
        with connection.cursor() as cursor:
            if join_table is None:
                cursor.execute(
                    f"""
                    DELETE FROM {table}
                    WHERE id IN (
                        SELECT id FROM {table}
                        WHERE pipeline_run_id = %s
                        ORDER BY id
                        LIMIT %s
                    )
                    """,
                    [pipeline_run_id, chunk_size],
                )
            else:
                cursor.execute(
                    f"""
                    DELETE FROM {table}
                    WHERE id IN (
                        SELECT child.id
                        FROM {table} child
                        JOIN {join_table} parent ON parent.id = child.{join_fk}
                        WHERE parent.pipeline_run_id = %s
                        ORDER BY child.id
                        LIMIT %s
                    )
                    """,
                    [pipeline_run_id, chunk_size],
                )
            deleted = cursor.rowcount if cursor.rowcount != -1 else 0

        total += deleted
        if deleted < chunk_size:
            break

    return total
