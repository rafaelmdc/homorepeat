from __future__ import annotations

DEFAULT_CHUNK_SIZE = 5_000


def delete_in_chunks(
    *,
    table: str,
    pipeline_run_id: int,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    join_table: str | None = None,
    join_fk: str | None = None,
) -> int:
    """Delete rows owned by pipeline_run_id in batches using CTE deletes.

    For direct ownership: table.pipeline_run_id = pipeline_run_id.
    For indirect children: join through join_table.join_fk -> RepeatCall.pipeline_run_id.

    Returns total rows deleted.
    """
    raise NotImplementedError
