from __future__ import annotations

import math
import os
from pathlib import Path
from uuid import UUID

from django.conf import settings
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction

from apps.imports.models import UploadedRun


class UploadValidationError(ValueError):
    pass


def start_upload(
    *,
    filename: str,
    size_bytes: int,
    total_chunks: int,
) -> UploadedRun:
    original_filename = Path(filename or "").name
    if not original_filename.lower().endswith(".zip"):
        raise UploadValidationError("Uploaded run must be a .zip file.")
    if size_bytes <= 0:
        raise UploadValidationError("Upload size must be greater than zero.")
    if size_bytes > settings.HOMOREPEAT_UPLOAD_MAX_ZIP_BYTES:
        raise UploadValidationError("Upload is larger than the configured maximum zip size.")

    chunk_size_bytes = settings.HOMOREPEAT_UPLOAD_CHUNK_BYTES
    expected_chunks = math.ceil(size_bytes / chunk_size_bytes)
    if total_chunks != expected_chunks:
        raise UploadValidationError(
            f"total_chunks must be {expected_chunks} for size_bytes={size_bytes}."
        )

    uploaded_run = UploadedRun.objects.create(
        original_filename=original_filename,
        size_bytes=size_bytes,
        chunk_size_bytes=chunk_size_bytes,
        total_chunks=total_chunks,
    )
    uploaded_run.upload_root.mkdir(parents=True, exist_ok=True)
    uploaded_run.chunks_root.mkdir(parents=True, exist_ok=True)
    return uploaded_run


def store_chunk(
    *,
    upload_id: UUID,
    chunk_index: int,
    chunk: UploadedFile,
) -> UploadedRun:
    uploaded_run = UploadedRun.objects.get(upload_id=upload_id)
    _validate_chunk(uploaded_run, chunk_index, chunk)

    uploaded_run.chunks_root.mkdir(parents=True, exist_ok=True)
    destination = uploaded_run.chunks_root / f"{chunk_index}.part"
    temporary_path = uploaded_run.chunks_root / f"{chunk_index}.part.tmp-{os.getpid()}"

    try:
        with temporary_path.open("wb") as output:
            for part in chunk.chunks():
                output.write(part)
        temporary_path.replace(destination)
    finally:
        temporary_path.unlink(missing_ok=True)

    with transaction.atomic():
        locked_upload = UploadedRun.objects.select_for_update().get(pk=uploaded_run.pk)
        received_chunks = _received_chunk_indexes(locked_upload.chunks_root)
        locked_upload.received_chunks = received_chunks
        locked_upload.received_bytes = _received_chunk_bytes(locked_upload.chunks_root, received_chunks)
        locked_upload.save(update_fields=["received_chunks", "received_bytes", "updated_at"])
        return locked_upload


def complete_upload(*, upload_id: UUID) -> UploadedRun:
    with transaction.atomic():
        uploaded_run = UploadedRun.objects.select_for_update().get(upload_id=upload_id)
        if uploaded_run.status in {
            UploadedRun.Status.RECEIVED,
            UploadedRun.Status.EXTRACTING,
            UploadedRun.Status.READY,
            UploadedRun.Status.QUEUED,
            UploadedRun.Status.IMPORTED,
        }:
            return uploaded_run
        if uploaded_run.status != UploadedRun.Status.RECEIVING:
            raise UploadValidationError("Upload cannot be completed from its current status.")

        received_chunks = _received_chunk_indexes(uploaded_run.chunks_root)
        expected_chunks = list(range(uploaded_run.total_chunks))
        if received_chunks != expected_chunks:
            missing_chunks = sorted(set(expected_chunks) - set(received_chunks))
            raise UploadValidationError(
                f"Upload is missing chunk(s): {', '.join(str(index) for index in missing_chunks)}"
            )

        received_bytes = _received_chunk_bytes(uploaded_run.chunks_root, received_chunks)
        if received_bytes != uploaded_run.size_bytes:
            raise UploadValidationError(
                f"Uploaded chunk bytes total {received_bytes}, expected {uploaded_run.size_bytes}."
            )

        uploaded_run.received_chunks = received_chunks
        uploaded_run.received_bytes = received_bytes
        uploaded_run.status = UploadedRun.Status.RECEIVED
        uploaded_run.save(update_fields=["received_chunks", "received_bytes", "status", "updated_at"])
        return uploaded_run


def _validate_chunk(uploaded_run: UploadedRun, chunk_index: int, chunk: UploadedFile) -> None:
    if uploaded_run.status != UploadedRun.Status.RECEIVING:
        raise UploadValidationError("Upload is not accepting chunks.")
    if chunk_index < 0 or chunk_index >= uploaded_run.total_chunks:
        raise UploadValidationError("Chunk index is outside the expected range.")
    if chunk.size <= 0:
        raise UploadValidationError("Chunk is empty.")
    if chunk.size > uploaded_run.chunk_size_bytes:
        raise UploadValidationError("Chunk is larger than the configured chunk size.")


def _received_chunk_indexes(chunks_root: Path) -> list[int]:
    indexes = []
    for path in chunks_root.glob("*.part"):
        try:
            indexes.append(int(path.stem))
        except ValueError:
            continue
    return sorted(indexes)


def _received_chunk_bytes(chunks_root: Path, received_chunks: list[int]) -> int:
    return sum((chunks_root / f"{index}.part").stat().st_size for index in received_chunks)
