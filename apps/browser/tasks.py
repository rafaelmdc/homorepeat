"""Celery tasks for the browser app.

Queue routing (declared in CELERY_TASK_ROUTES in config/settings.py):
  payload_graph — run_post_import_warmup, warm_stats_bundle
  downloads     — generate_download_artifact, expire_stale_download_builds
"""
import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task
def run_post_import_warmup(catalog_version: int) -> None:
    """Fan out cache pre-warming tasks for the default scope after a successful import.

    Dispatches one warm_stats_bundle task per bundle type in WARMUP_BUILD_TYPES.
    Uses get_or_create so re-running for the same catalog_version is idempotent.
    Only enqueues a new warm_stats_bundle task when a fresh PayloadBuild row
    is created; already-queued or completed builds are left untouched.
    """
    from apps.browser.models import PayloadBuild
    from apps.browser.stats.warmup import (
        WARMUP_BUILD_TYPES,
        compute_scope_key,
        default_warmup_scope_params,
    )

    scope_params = default_warmup_scope_params()
    scope_key = compute_scope_key(scope_params)

    for build_type in WARMUP_BUILD_TYPES:
        build, created = PayloadBuild.objects.get_or_create(
            build_type=build_type,
            scope_key=scope_key,
            catalog_version=catalog_version,
            defaults={
                "status": PayloadBuild.Status.PENDING,
                "scope_params": scope_params,
            },
        )
        if created:
            warm_stats_bundle.delay(build.pk)
            logger.info(
                "payload_warmup enqueued build_type=%s catalog_version=%d pk=%d",
                build_type,
                catalog_version,
                build.pk,
            )
        else:
            logger.debug(
                "payload_warmup skipped existing build_type=%s catalog_version=%d status=%s",
                build_type,
                catalog_version,
                build.status,
            )


@shared_task(bind=True, max_retries=3)
def warm_stats_bundle(self, payload_build_id: int) -> None:
    """Pre-warm one stats bundle into the shared Redis cache.

    Atomically claims the PayloadBuild (PENDING → BUILDING), reconstructs
    the filter state from scope_params, calls the bundle builder (which
    stores the result in Redis via build_or_get_cached), then marks the
    build READY. Failed builds are retried up to max_retries times with a
    30-second countdown; if all retries are exhausted the build is marked FAILED.
    """
    from apps.browser.models import PayloadBuild
    from apps.browser.stats.filters import build_stats_filter_state_from_params
    from apps.browser.stats.warmup import get_bundle_builders

    try:
        build = PayloadBuild.objects.get(pk=payload_build_id)
    except PayloadBuild.DoesNotExist:
        logger.warning("warm_stats_bundle: PayloadBuild %d not found", payload_build_id)
        return

    # Atomic claim: only proceed if still PENDING.
    claimed = PayloadBuild.objects.filter(
        pk=payload_build_id,
        status=PayloadBuild.Status.PENDING,
    ).update(
        status=PayloadBuild.Status.BUILDING,
        started_at=timezone.now(),
        celery_task_id=self.request.id or "",
    )
    if not claimed:
        logger.info(
            "warm_stats_bundle: PayloadBuild %d already claimed (status=%s)",
            payload_build_id,
            build.status,
        )
        return

    builders = get_bundle_builders()
    builder = builders.get(build.build_type)
    if builder is None:
        logger.error("warm_stats_bundle: unknown build_type=%r pk=%d", build.build_type, payload_build_id)
        PayloadBuild.objects.filter(pk=payload_build_id).update(
            status=PayloadBuild.Status.FAILED,
            error_message=f"Unknown build_type: {build.build_type!r}",
            finished_at=timezone.now(),
        )
        return

    try:
        filter_state = build_stats_filter_state_from_params(build.scope_params)
        builder(filter_state)
        PayloadBuild.objects.filter(pk=payload_build_id).update(
            status=PayloadBuild.Status.READY,
            finished_at=timezone.now(),
        )
        logger.info(
            "warm_stats_bundle: ready build_type=%s pk=%d",
            build.build_type,
            payload_build_id,
        )
    except Exception as exc:
        logger.warning(
            "warm_stats_bundle: error build_type=%s pk=%d: %s",
            build.build_type,
            payload_build_id,
            exc,
        )
        if self.request.retries < self.max_retries:
            # Reset to PENDING so the next attempt can reclaim via the atomic claim.
            PayloadBuild.objects.filter(pk=payload_build_id).update(
                status=PayloadBuild.Status.PENDING,
            )
            raise self.retry(exc=exc, countdown=30)
        else:
            PayloadBuild.objects.filter(pk=payload_build_id).update(
                status=PayloadBuild.Status.FAILED,
                error_message=str(exc)[:2000],
                finished_at=timezone.now(),
            )


@shared_task
def expire_stale_download_builds() -> dict[str, int]:
    """Expire stale DownloadBuild rows on a scheduled cadence.

    Marks PENDING/BUILDING rows older than 1 hour as EXPIRED (stuck jobs that
    never completed). Marks READY rows older than 7 days as EXPIRED (artifact
    retention window). Runs periodically via Celery Beat on the downloads queue.
    """
    from apps.browser.models import DownloadBuild

    now = timezone.now()
    stuck = DownloadBuild.objects.filter(
        status__in=[DownloadBuild.Status.PENDING, DownloadBuild.Status.BUILDING],
        created_at__lt=now - timedelta(hours=1),
    ).update(status=DownloadBuild.Status.EXPIRED)

    aged = DownloadBuild.objects.filter(
        status=DownloadBuild.Status.READY,
        finished_at__lt=now - timedelta(days=7),
    ).update(status=DownloadBuild.Status.EXPIRED)

    if stuck or aged:
        logger.info("download_builds expired: stuck=%d aged=%d", stuck, aged)
    return {"stuck": stuck, "aged": aged}


@shared_task(bind=True, max_retries=3)
def generate_download_artifact(self, download_build_id: int) -> None:
    """Build a download artifact file on the downloads queue.

    Not yet activated for any download type. To activate: add a DownloadBuildType
    to _ASYNC_ARTIFACT_TYPES in apps/browser/downloads.py, implement the
    artifact generation logic below, and wire the task dispatch in the view.
    """
    raise NotImplementedError(
        "generate_download_artifact is not yet wired to any download type. "
        "Activate by adding a DownloadBuildType to _ASYNC_ARTIFACT_TYPES in "
        "apps/browser/downloads.py and implementing artifact generation here."
    )
