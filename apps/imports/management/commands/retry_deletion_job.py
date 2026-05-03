from django.core.management.base import BaseCommand, CommandError

from apps.imports.models import DeletionJob
from apps.imports.services.deletion.jobs import retry_deletion
from apps.imports.services.deletion.safety import DeletionTargetError


class Command(BaseCommand):
    help = "Retry a failed DeletionJob. Only failed jobs are eligible."

    def add_arguments(self, parser):
        parser.add_argument("--job-id", required=True, type=int, help="Primary key of the DeletionJob to retry.")
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="Actually re-enqueue the job. Omit to perform a read-only check.",
        )

    def handle(self, *args, **options):
        job_id = options["job_id"]
        confirm = options["confirm"]

        job = (
            DeletionJob.objects.select_related("pipeline_run")
            .filter(pk=job_id)
            .first()
        )
        if job is None:
            raise CommandError(f"No DeletionJob found with id={job_id}.")

        run = job.pipeline_run
        run_label = run.run_id if run else "—"

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("=== Retry Check ==="))
        self.stdout.write(f"  job_id        : {job.pk}")
        self.stdout.write(f"  status        : {job.status}")
        self.stdout.write(f"  target run_id : {run_label}")
        self.stdout.write(f"  retry count   : {job.retry_count}")
        if job.error_message:
            self.stdout.write(self.style.ERROR(f"  last error    : {job.error_message}"))
        self.stdout.write("")

        if job.status != DeletionJob.Status.FAILED:
            raise CommandError(
                f"DeletionJob {job.pk} has status={job.status!r}. Only failed jobs can be retried."
            )

        if not confirm:
            self.stdout.write(
                self.style.WARNING(
                    "Dry-run complete. No data was modified. "
                    "Pass --confirm to re-enqueue the job."
                )
            )
            return

        try:
            updated_job = retry_deletion(job)
        except DeletionTargetError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS(
            f"DeletionJob {updated_job.pk} re-enqueued "
            f"(status={updated_job.status}, retry_count={updated_job.retry_count})."
        ))
        self.stdout.write(
            f"  Check progress : python manage.py deletion_status --job-id {updated_job.pk}"
        )
