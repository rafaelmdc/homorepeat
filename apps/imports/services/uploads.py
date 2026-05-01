from __future__ import annotations

import hashlib
import math
import os
import re
import shutil
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from django.conf import settings
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction

from apps.imports.models import ImportBatch, UploadedRun, UploadedRunChunk
from apps.imports.services.published_run import inspect_published_run

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class UploadValidationError(ValueError):
    pass


@dataclass(frozen=True)
class CompletedUpload:
    uploaded_run: UploadedRun
    completed_now: bool


@dataclass(frozen=True)
class QueuedUploadedRunImport:
    uploaded_run: UploadedRun
    import_batch: ImportBatch
    queued_now: bool


def start_upload(
    *,
    filename: str,
    size_bytes: int,
    total_chunks: int,
    file_sha256: str | None = None,
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

    if file_sha256 is not None and not _is_valid_sha256(file_sha256):
        raise UploadValidationError(
            "file_sha256 must be a 64-character lowercase hex string."
        )

    Path(settings.HOMOREPEAT_IMPORTS_ROOT).mkdir(parents=True, exist_ok=True)
    _check_disk_space_for_upload(size_bytes)

    uploaded_run = UploadedRun.objects.create(
        original_filename=original_filename,
        size_bytes=size_bytes,
        chunk_size_bytes=chunk_size_bytes,
        total_chunks=total_chunks,
        file_sha256=file_sha256,
    )
    uploaded_run.upload_root.mkdir(parents=True, exist_ok=True)
    uploaded_run.chunks_root.mkdir(parents=True, exist_ok=True)
    return uploaded_run


def store_chunk(
    *,
    upload_id: UUID,
    chunk_index: int,
    chunk: UploadedFile,
    chunk_sha256: str | None = None,
) -> UploadedRun:
    uploaded_run = UploadedRun.objects.get(upload_id=upload_id)
    _validate_chunk(uploaded_run, chunk_index, chunk)

    if chunk_sha256 is not None and not _is_valid_sha256(chunk_sha256):
        raise UploadValidationError("chunk_sha256 must be a 64-character lowercase hex string.")

    uploaded_run.chunks_root.mkdir(parents=True, exist_ok=True)
    destination = uploaded_run.chunks_root / f"{chunk_index}.part"
    temporary_path = uploaded_run.chunks_root / f"{chunk_index}.part.tmp-{os.getpid()}"

    hasher = hashlib.sha256()
    try:
        with temporary_path.open("wb") as output:
            for part in chunk.chunks():
                output.write(part)
                hasher.update(part)
        computed_sha256 = hasher.hexdigest()

        if chunk_sha256 is not None and computed_sha256 != chunk_sha256:
            raise UploadValidationError(
                f"Chunk {chunk_index} checksum mismatch: expected {chunk_sha256}, got {computed_sha256}."
            )

        with transaction.atomic():
            locked_upload = UploadedRun.objects.select_for_update().get(pk=uploaded_run.pk)

            existing_record = UploadedRunChunk.objects.filter(
                uploaded_run=locked_upload,
                chunk_index=chunk_index,
            ).first()

            if existing_record is not None:
                if existing_record.sha256 == computed_sha256:
                    return locked_upload
                raise UploadValidationError(
                    f"Chunk {chunk_index} conflicts with an already accepted chunk."
                )

            temporary_path.replace(destination)

            received_chunks = _received_chunk_indexes(locked_upload.chunks_root)
            locked_upload.received_chunks = received_chunks
            locked_upload.received_bytes = _received_chunk_bytes(locked_upload.chunks_root, received_chunks)
            locked_upload.save(update_fields=["received_chunks", "received_bytes", "updated_at"])

            UploadedRunChunk.objects.create(
                uploaded_run=locked_upload,
                chunk_index=chunk_index,
                size_bytes=destination.stat().st_size,
                sha256=computed_sha256,
            )

            return locked_upload
    finally:
        temporary_path.unlink(missing_ok=True)


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


def queue_uploaded_run_import(
    *,
    upload_id: UUID,
    replace_existing: bool = False,
) -> QueuedUploadedRunImport:
    queued_now = False

    with transaction.atomic():
        uploaded_run = UploadedRun.objects.select_for_update().get(upload_id=upload_id)
        if uploaded_run.status in {
            UploadedRun.Status.QUEUED,
            UploadedRun.Status.IMPORTED,
        }:
            if uploaded_run.import_batch_id is None:
                raise UploadValidationError("Uploaded run is marked queued but has no linked import batch.")
            import_batch = ImportBatch.objects.get(pk=uploaded_run.import_batch_id)
            return QueuedUploadedRunImport(
                uploaded_run=uploaded_run,
                import_batch=import_batch,
                queued_now=False,
            )
        if uploaded_run.status != UploadedRun.Status.READY:
            raise UploadValidationError("Uploaded run is not ready for import.")
        if not uploaded_run.publish_root:
            raise UploadValidationError("Uploaded run does not have a validated publish root.")

        from apps.imports.services.import_run.api import enqueue_published_run

        import_batch = enqueue_published_run(
            uploaded_run.publish_root,
            replace_existing=replace_existing,
        )
        uploaded_run.import_batch = import_batch
        uploaded_run.status = UploadedRun.Status.QUEUED
        uploaded_run.save(update_fields=["import_batch", "status", "updated_at"])
        queued_now = True

    if queued_now:
        from apps.imports.services.import_run.api import dispatch_import_batch

        dispatch_import_batch(import_batch)
        import_batch.refresh_from_db()
        uploaded_run.refresh_from_db()

    return QueuedUploadedRunImport(
        uploaded_run=uploaded_run,
        import_batch=import_batch,
        queued_now=queued_now,
    )


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

        _check_disk_space_for_extraction(uploaded_run)

        uploaded_run.received_chunks = received_chunks
        uploaded_run.received_bytes = received_bytes
        uploaded_run.status = UploadedRun.Status.EXTRACTING
        uploaded_run.save(update_fields=["received_chunks", "received_bytes", "status", "updated_at"])

    temporary_path = uploaded_run.upload_root / f"source.zip.tmp-{os.getpid()}"
    try:
        hasher = hashlib.sha256()
        with temporary_path.open("wb") as output:
            for chunk_index in uploaded_run.received_chunks:
                with (uploaded_run.chunks_root / f"{chunk_index}.part").open("rb") as source:
                    while True:
                        buf = source.read(256 * 1024)
                        if not buf:
                            break
                        output.write(buf)
                        hasher.update(buf)
        assembled_sha256 = hasher.hexdigest()

        if uploaded_run.file_sha256 and assembled_sha256 != uploaded_run.file_sha256:
            with transaction.atomic():
                locked = UploadedRun.objects.select_for_update().get(pk=uploaded_run_id)
                locked.assembled_sha256 = assembled_sha256
                locked.checksum_status = "failed"
                locked.checksum_error = (
                    f"Assembled SHA-256 {assembled_sha256} does not match "
                    f"declared {uploaded_run.file_sha256}."
                )
                locked.status = UploadedRun.Status.FAILED
                locked.save(update_fields=[
                    "assembled_sha256", "checksum_status", "checksum_error",
                    "status", "updated_at",
                ])
            raise UploadValidationError(
                "Assembled zip checksum does not match the declared file_sha256."
            )

        temporary_path.replace(uploaded_run.zip_path)

        with transaction.atomic():
            locked = UploadedRun.objects.select_for_update().get(pk=uploaded_run_id)
            locked.assembled_sha256 = assembled_sha256
            if uploaded_run.file_sha256:
                locked.checksum_status = "ok"
            locked.save(update_fields=["assembled_sha256", "checksum_status", "updated_at"])
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

    publish_root = find_publish_root(uploaded_run.extracted_root)
    inspected = inspect_published_run(publish_root)
    uploaded_run.run_id = str(inspected.pipeline_run["run_id"])
    uploaded_run.save(update_fields=["run_id", "updated_at"])
    return move_to_library(uploaded_run=uploaded_run, publish_root=publish_root)


def move_to_library(*, uploaded_run: UploadedRun, publish_root: Path) -> UploadedRun:
    if not uploaded_run.run_id:
        raise UploadValidationError("Uploaded run does not have a validated run_id.")
    library_root = uploaded_run.library_root
    if library_root is None:
        raise UploadValidationError("Uploaded run library path could not be resolved.")
    final_publish_root = library_root / "publish"

    try:
        library_root.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise UploadValidationError(
            f"Run {uploaded_run.run_id!r} already exists in the upload library."
        ) from exc

    try:
        shutil.copytree(publish_root, final_publish_root)
    except Exception:
        shutil.rmtree(library_root, ignore_errors=True)
        raise

    uploaded_run.publish_root = str(final_publish_root.resolve())
    uploaded_run.status = UploadedRun.Status.READY
    uploaded_run.save(update_fields=["publish_root", "status", "updated_at"])
    return uploaded_run


def find_publish_root(extracted_root: Path) -> Path:
    manifest_paths = [
        path
        for path in extracted_root.rglob("run_manifest.json")
        if path.parent.name == "metadata" and path.parent.parent.name == "publish"
    ]
    if not manifest_paths:
        raise UploadValidationError("Extracted upload does not contain publish/metadata/run_manifest.json.")
    if len(manifest_paths) > 1:
        raise UploadValidationError("Extracted upload contains multiple publish/metadata/run_manifest.json files.")
    return manifest_paths[0].parent.parent


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


def _is_valid_sha256(value: str) -> bool:
    return bool(_SHA256_RE.match(value))


def _imports_root_disk_usage():
    """Return disk usage for the imports root, walking up to find an existing ancestor."""
    path = Path(settings.HOMOREPEAT_IMPORTS_ROOT)
    while not path.exists():
        path = path.parent
    return shutil.disk_usage(path)


def _check_disk_space_for_upload(size_bytes: int) -> None:
    if not settings.HOMOREPEAT_UPLOAD_DISK_PREFLIGHT_ENABLED:
        return
    usage = _imports_root_disk_usage()
    min_free = settings.HOMOREPEAT_UPLOAD_MIN_FREE_BYTES
    # Peak during upload: all chunks present + zip temp being assembled in parallel
    required = size_bytes * 2 + min_free
    if usage.free < required:
        raise UploadValidationError(
            f"Insufficient disk space to accept this upload: "
            f"{required:,} bytes required ({size_bytes:,} chunks + "
            f"{size_bytes:,} assembled zip + {min_free:,} reserved), "
            f"but only {usage.free:,} bytes are free."
        )


def _check_disk_space_for_extraction(uploaded_run: UploadedRun) -> None:
    if not settings.HOMOREPEAT_UPLOAD_DISK_PREFLIGHT_ENABLED:
        return
    usage = _imports_root_disk_usage()
    min_free = settings.HOMOREPEAT_UPLOAD_MIN_FREE_BYTES
    multiplier = settings.HOMOREPEAT_UPLOAD_EXTRACTION_SPACE_MULTIPLIER
    extraction_estimate = int(
        min(
            uploaded_run.size_bytes * multiplier,
            settings.HOMOREPEAT_UPLOAD_MAX_EXTRACTED_BYTES,
        )
    )
    # Need space for: extracted working dir + final library copy + safety margin
    required = extraction_estimate * 2 + min_free
    if usage.free < required:
        raise UploadValidationError(
            f"Insufficient disk space to extract this upload: "
            f"{required:,} bytes required ({extraction_estimate:,} extracted + "
            f"{extraction_estimate:,} library copy + {min_free:,} reserved), "
            f"but only {usage.free:,} bytes are free."
        )


def get_upload_status(*, upload_id: UUID) -> dict:
    """Return a reconciled status dict for an upload.

    Filesystem presence is authoritative for which chunks exist. The
    UploadedRunChunk table provides sha256 and size metadata. When the two
    diverge (e.g. after a worker crash), filesystem-present chunks are
    included with sha256=null so the browser knows to re-upload them.
    """
    uploaded_run = UploadedRun.objects.get(upload_id=upload_id)

    chunks_root = uploaded_run.chunks_root
    fs_chunk_indexes = _received_chunk_indexes(chunks_root) if chunks_root.exists() else []

    db_chunks: dict[int, UploadedRunChunk] = {
        record.chunk_index: record
        for record in UploadedRunChunk.objects.filter(uploaded_run=uploaded_run)
    }

    received_chunks = []
    for chunk_index in fs_chunk_indexes:
        db_record = db_chunks.get(chunk_index)
        chunk_path = chunks_root / f"{chunk_index}.part"
        received_chunks.append(
            {
                "index": chunk_index,
                "size_bytes": chunk_path.stat().st_size if chunk_path.exists() else (db_record.size_bytes if db_record else 0),
                "sha256": db_record.sha256 if db_record else None,
            }
        )

    import_batch_payload = None
    if uploaded_run.import_batch_id:
        batch = uploaded_run.import_batch
        import_batch_payload = {
            "id": batch.pk,
            "status": batch.status,
            "phase": batch.phase,
        }

    return {
        "upload_id": str(uploaded_run.upload_id),
        "status": uploaded_run.status,
        "filename": uploaded_run.original_filename,
        "size_bytes": uploaded_run.size_bytes,
        "chunk_size_bytes": uploaded_run.chunk_size_bytes,
        "total_chunks": uploaded_run.total_chunks,
        "received_chunks": received_chunks,
        "received_bytes": sum(c["size_bytes"] for c in received_chunks),
        "file_sha256": uploaded_run.file_sha256,
        "checksum_status": uploaded_run.checksum_status,
        "import_batch": import_batch_payload,
        "allowed_actions": _allowed_actions(uploaded_run, fs_chunk_indexes),
    }


def _allowed_actions(uploaded_run: UploadedRun, fs_chunk_indexes: list[int]) -> list[str]:
    if uploaded_run.status == UploadedRun.Status.RECEIVING:
        missing = set(range(uploaded_run.total_chunks)) - set(fs_chunk_indexes)
        if missing:
            return ["upload_chunks"]
        return ["upload_chunks", "complete"]
    if uploaded_run.status == UploadedRun.Status.RECEIVED:
        return ["wait"]
    if uploaded_run.status == UploadedRun.Status.EXTRACTING:
        return ["wait"]
    if uploaded_run.status == UploadedRun.Status.READY:
        return ["import"]
    if uploaded_run.status in {UploadedRun.Status.QUEUED, UploadedRun.Status.IMPORTED}:
        return ["wait"]
    if uploaded_run.status == UploadedRun.Status.FAILED:
        return ["clear"]
    return []
