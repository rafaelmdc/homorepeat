from __future__ import annotations

import math
import os
import shutil
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from django.conf import settings
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction

from apps.imports.models import UploadedRun


class UploadValidationError(ValueError):
    pass


@dataclass(frozen=True)
class CompletedUpload:
    uploaded_run: UploadedRun
    completed_now: bool


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


def complete_upload(*, upload_id: UUID) -> CompletedUpload:
    with transaction.atomic():
        uploaded_run = UploadedRun.objects.select_for_update().get(upload_id=upload_id)
        if uploaded_run.status in {
            UploadedRun.Status.RECEIVED,
            UploadedRun.Status.EXTRACTING,
            UploadedRun.Status.READY,
            UploadedRun.Status.QUEUED,
            UploadedRun.Status.IMPORTED,
        }:
            return CompletedUpload(uploaded_run=uploaded_run, completed_now=False)
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
        return CompletedUpload(uploaded_run=uploaded_run, completed_now=True)


def assemble_uploaded_zip(*, uploaded_run_id: int) -> UploadedRun:
    with transaction.atomic():
        uploaded_run = UploadedRun.objects.select_for_update().get(pk=uploaded_run_id)
        if uploaded_run.status in {
            UploadedRun.Status.READY,
            UploadedRun.Status.QUEUED,
            UploadedRun.Status.IMPORTED,
        }:
            return uploaded_run
        if uploaded_run.status == UploadedRun.Status.EXTRACTING and uploaded_run.zip_path.is_file():
            return uploaded_run
        if uploaded_run.status not in {UploadedRun.Status.RECEIVED, UploadedRun.Status.EXTRACTING}:
            raise UploadValidationError("Upload is not ready for extraction.")

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
        uploaded_run.status = UploadedRun.Status.EXTRACTING
        uploaded_run.save(update_fields=["received_chunks", "received_bytes", "status", "updated_at"])

    temporary_path = uploaded_run.upload_root / f"source.zip.tmp-{os.getpid()}"
    try:
        with temporary_path.open("wb") as output:
            for chunk_index in uploaded_run.received_chunks:
                with (uploaded_run.chunks_root / f"{chunk_index}.part").open("rb") as source:
                    shutil.copyfileobj(source, output)
        temporary_path.replace(uploaded_run.zip_path)
    finally:
        temporary_path.unlink(missing_ok=True)

    uploaded_run.refresh_from_db()
    return uploaded_run


def extract_uploaded_zip(*, uploaded_run_id: int) -> UploadedRun:
    uploaded_run = assemble_uploaded_zip(uploaded_run_id=uploaded_run_id)
    if uploaded_run.status in {
        UploadedRun.Status.READY,
        UploadedRun.Status.QUEUED,
        UploadedRun.Status.IMPORTED,
    }:
        return uploaded_run
    if uploaded_run.status != UploadedRun.Status.EXTRACTING:
        raise UploadValidationError("Upload is not ready for extraction.")
    if not zipfile.is_zipfile(uploaded_run.zip_path):
        raise UploadValidationError("Uploaded file is not a valid zip archive.")

    if uploaded_run.extracted_root.exists():
        shutil.rmtree(uploaded_run.extracted_root)
    uploaded_run.extracted_root.mkdir(parents=True)

    total_extracted_bytes = 0
    extracted_files = 0
    extracted_root = uploaded_run.extracted_root.resolve()

    try:
        with zipfile.ZipFile(uploaded_run.zip_path) as archive:
            members = archive.infolist()
            if len(members) > settings.HOMOREPEAT_UPLOAD_MAX_FILES:
                raise UploadValidationError(
                    f"Zip contains {len(members)} entries; maximum is {settings.HOMOREPEAT_UPLOAD_MAX_FILES}."
                )

            for member in members:
                _validate_zip_member(member, extracted_root)
                if member.is_dir():
                    target_dir = (uploaded_run.extracted_root / member.filename).resolve()
                    _ensure_within_root(target_dir, extracted_root)
                    target_dir.mkdir(parents=True, exist_ok=True)
                    continue

                total_extracted_bytes += member.file_size
                if total_extracted_bytes > settings.HOMOREPEAT_UPLOAD_MAX_EXTRACTED_BYTES:
                    raise UploadValidationError("Zip extracted size exceeds the configured limit.")
                extracted_files += 1
                if extracted_files > settings.HOMOREPEAT_UPLOAD_MAX_FILES:
                    raise UploadValidationError(
                        f"Zip contains more than {settings.HOMOREPEAT_UPLOAD_MAX_FILES} files."
                    )

                target_path = (uploaded_run.extracted_root / member.filename).resolve()
                _ensure_within_root(target_path, extracted_root)
                target_path.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, target_path.open("wb") as destination:
                    shutil.copyfileobj(source, destination)
    except zipfile.BadZipFile as exc:
        raise UploadValidationError("Uploaded file is not a valid zip archive.") from exc
    except UploadValidationError:
        shutil.rmtree(uploaded_run.extracted_root, ignore_errors=True)
        raise

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


def _validate_zip_member(member: zipfile.ZipInfo, extracted_root: Path) -> None:
    member_path = Path(member.filename)
    if member_path.is_absolute():
        raise UploadValidationError("Zip archive contains an absolute path.")
    if ".." in member_path.parts:
        raise UploadValidationError("Zip archive contains path traversal.")

    file_type = stat.S_IFMT(member.external_attr >> 16)
    if file_type in {stat.S_IFLNK, stat.S_IFCHR, stat.S_IFBLK, stat.S_IFIFO, stat.S_IFSOCK}:
        raise UploadValidationError("Zip archive contains a symlink or special file.")

    target_path = (extracted_root / member.filename).resolve()
    _ensure_within_root(target_path, extracted_root)


def _ensure_within_root(path: Path, root: Path) -> None:
    if path != root and root not in path.parents:
        raise UploadValidationError("Zip archive contains a path outside the extraction root.")
