from django.core.management.base import BaseCommand, CommandError

from apps.browser.models import PipelineRun
from apps.imports.services.deletion.jobs import queue_deletion
from apps.imports.services.deletion.planning import build_deletion_plan
from apps.imports.services.deletion.safety import DeletionTargetError, validate_deletion_target

LARGE_ROW_THRESHOLD = 500_000


class Command(BaseCommand):
    help = "Queue a PipelineRun for deletion. Dry-run by default; pass --confirm to enqueue."

    def add_arguments(self, parser):
        parser.add_argument("--run-id", required=True, help="run_id of the PipelineRun to delete.")
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="Actually queue the deletion job. Omit to perform a read-only dry-run.",
        )
        parser.add_argument("--reason", default="", help="Human-readable reason for deletion (recorded on job).")

    def handle(self, *args, **options):
        run_id = options["run_id"]
        confirm = options["confirm"]
        reason = options["reason"]

        pipeline_run = PipelineRun.objects.filter(run_id=run_id).first()
        if pipeline_run is None:
            raise CommandError(f"No PipelineRun found with run_id={run_id!r}.")

        try:
            validate_deletion_target(pipeline_run)
        except DeletionTargetError as exc:
            raise CommandError(str(exc)) from exc

        plan = build_deletion_plan(pipeline_run)

        self._print_plan(plan, run_id, confirm)

        if not confirm:
            self.stdout.write(
                self.style.WARNING(
                    "\nDry-run complete. No data was modified. "
                    "Pass --confirm to queue the deletion job."
                )
            )
            return

        job = queue_deletion(pipeline_run, reason=reason)

        self.stdout.write("")
        if plan.active_job_id == job.pk:
            self.stdout.write(
                self.style.WARNING(f"Reused existing active job (id={job.pk}, status={job.status}).")
            )
        else:
            self.stdout.write(self.style.SUCCESS(f"Deletion job queued (id={job.pk}, status={job.status})."))
        self.stdout.write(f"  Check progress : python manage.py deletion_status --job-id {job.pk}")

    def _print_plan(self, plan, run_id, confirm):
        w = self.stdout.write
        style = self.style

        w("")
        w(style.MIGRATE_HEADING("=== Deletion Plan ==="))
        w(f"  run_id          : {plan.run_id}")
        w(f"  pipeline_run_id : {plan.pipeline_run_id}")
        w(f"  lifecycle_status: {plan.lifecycle_status}")
        w(f"  active_job_id   : {plan.active_job_id or '—'}")
        w(f"  catalog_version : {plan.catalog_version}")
        w("")

        w(style.MIGRATE_HEADING("--- Tables ---"))
        action_order = ["delete", "repair", "rebuild", "retain", "never_touch"]
        for action in action_order:
            rows = [t for t in plan.tables if t.action == action]
            if not rows:
                continue
            label = {
                "delete": "DELETE",
                "repair": "REPAIR (canonical)",
                "rebuild": "REBUILD (rollup)",
                "retain": "RETAIN (audit)",
                "never_touch": "NEVER TOUCH",
            }[action]
            w(f"  {label}")
            for t in rows:
                row_str = f"{t.row_count:>10,}" if t.action not in ("never_touch", "rebuild") else "         —"
                estimated = " (estimated)" if t.estimated else ""
                notes = f"  # {t.notes}" if t.notes else ""
                w(f"    {t.table:<50} {row_str}{estimated}{notes}")
        w("")

        w(style.MIGRATE_HEADING("--- Summary ---"))
        w(f"  Total rows to delete   : {plan.total_rows_to_delete:,}")
        w(f"  Canonical rows impacted: {plan.total_canonical_impacted:,}")
        w("")

        if plan.artifact_roots:
            w(style.MIGRATE_HEADING("--- Artifact roots ---"))
            for root in plan.artifact_roots:
                w(f"  {root}")
            w("")

        if plan.warnings:
            w(style.WARNING("--- Warnings ---"))
            for warning in plan.warnings:
                w(style.WARNING(f"  ! {warning}"))
            w("")
