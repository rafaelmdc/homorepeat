from __future__ import annotations

import csv
from io import StringIO
from typing import Iterable

from django.db import DEFAULT_DB_ALIAS, connections


BULK_CREATE_BATCH_SIZE = 5000
COPY_FLUSH_ROW_COUNT = 10000
COPY_FLUSH_BYTE_COUNT = 8 * 1024 * 1024


def _copy_rows_to_table(
    table_name: str,
    column_names: list[str],
    rows: Iterable[tuple[object, ...]],
) -> int | None:
    connection = connections[DEFAULT_DB_ALIAS]
    if connection.vendor != "postgresql":
        return None

    connection.ensure_connection()
    with connection.cursor() as cursor_wrapper:
        raw_cursor = getattr(cursor_wrapper, "cursor", None)
        if raw_cursor is None or not hasattr(raw_cursor, "copy"):
            return None

        quoted_table = connection.ops.quote_name(table_name)
        quoted_columns = ", ".join(connection.ops.quote_name(column_name) for column_name in column_names)
        count = 0
        buffer = StringIO()
        writer = csv.writer(
            buffer,
            delimiter="\t",
            quotechar='"',
            lineterminator="\n",
            quoting=csv.QUOTE_MINIMAL,
        )

        def flush_buffer(copy) -> None:
            payload = buffer.getvalue()
            if not payload:
                return
            copy.write(payload)
            buffer.seek(0)
            buffer.truncate(0)

        with raw_cursor.copy(
            f"COPY {quoted_table} ({quoted_columns}) FROM STDIN WITH (FORMAT CSV, DELIMITER E'\\t', NULL '\\N')"
        ) as copy:
            for row in rows:
                writer.writerow(_serialize_copy_row(row))
                count += 1
                if count % COPY_FLUSH_ROW_COUNT == 0 or buffer.tell() >= COPY_FLUSH_BYTE_COUNT:
                    flush_buffer(copy)
            flush_buffer(copy)

    return count


def _serialize_copy_row(row: tuple[object, ...]) -> tuple[str, ...]:
    return tuple(_serialize_copy_value(value) for value in row)


def _serialize_copy_value(value: object) -> str:
    if value is None:
        return r"\N"
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat(sep=" ")
        except TypeError:
            return value.isoformat()
    return str(value)


def _analyze_models(models: Iterable[type]) -> bool:
    connection = connections[DEFAULT_DB_ALIAS]
    if connection.vendor != "postgresql":
        return False
    try:
        with connection.cursor() as cursor:
            for model in models:
                cursor.execute(f"ANALYZE {connection.ops.quote_name(model._meta.db_table)}")
    except Exception:
        return False
    return True
