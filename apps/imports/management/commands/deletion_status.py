from django.core.management.base import BaseCommand, CommandError

from apps.imports.models import DeletionJob


class Command(BaseCommand):
    help = "Show the status of a DeletionJob."

    def add_arguments(self, parser):
        parser.add_argument("--job-id", required=True, type=int, help="Primary key of the DeletionJob.")

    def handle(self, *args, **options):
        job_id = options["job_id"]

        job = (
            DeletionJob.objects.select_related("pipeline_run")
            .filter(pk=job_id)
            .first()
        )
        if job is None:
            raise CommandError(f"No DeletionJob found with id={job_id}.")

        w = self.stdout.write
        style = self.style

        run = job.pipeline_run
        run_label = run.run_id if run else "—"
        run_lifecycle = run.lifecycle_status if run else "—"

        status_style = {
            DeletionJob.Status.PENDING: style.WARNING,
            DeletionJob.Status.RUNNING: style.MIGRATE_LABEL,
            DeletionJob.Status.DONE: style.SUCCESS,
            DeletionJob.Status.FAILED: style.ERROR,
        }.get(job.status, lambda x: x)

        w("")
        w(style.MIGRATE_HEADING("=== Deletion Job Status ==="))
        w(f"  job_id          : {job.pk}")
        w(f"  status          : {status_style(job.status)}")
        w(f"  phase           : {job.phase or '—'}")
        w(f"  target run_id   : {run_label}")
        w(f"  run lifecycle   : {run_lifecycle}")
        w(f"  reason          : {job.reason or '—'}")
        w(f"  requested_by    : {job.requested_by_label or '—'}")
        w("")

        w(style.MIGRATE_HEADING("--- Timestamps ---"))
        w(f"  created_at      : {job.created_at}")
        w(f"  started_at      : {job.started_at or '—'}")
        w(f"  finished_at     : {job.finished_at or '—'}")
        w(f"  last_heartbeat  : {job.last_heartbeat_at or '—'}")
        w("")

        w(style.MIGRATE_HEADING("--- Progress ---"))
        w(f"  rows planned    : {job.rows_planned:,}")
        w(f"  rows deleted    : {job.rows_deleted:,}")
        w(f"  artifacts planned: {job.artifacts_planned:,}")
        w(f"  artifacts deleted: {job.artifacts_deleted:,}")
        w(f"  current table   : {job.current_table or '—'}")
        w(f"  retry count     : {job.retry_count}")
        w(f"  catalog versions: {job.catalog_versions or '—'}")
        w("")

        if job.error_message:
            w(style.ERROR("--- Error ---"))
            w(style.ERROR(f"  {job.error_message}"))
            w("")

        if job.status == DeletionJob.Status.FAILED:
            w(style.WARNING(
                f"  To retry: python manage.py retry_deletion_job --job-id {job.pk} --confirm"
            ))
            w("")
