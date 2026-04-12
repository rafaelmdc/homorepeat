from django.core.management.base import BaseCommand, CommandError

from apps.browser.metadata import backfill_run_browser_metadata
from apps.browser.models import PipelineRun


class Command(BaseCommand):
    help = "Backfill PipelineRun.browser_metadata from completed import batches and small-table facets."

    def add_arguments(self, parser):
        parser.add_argument(
            "--run-id",
            help="Only backfill one imported run by run_id.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Recompute and overwrite existing browser_metadata.",
        )

    def handle(self, *args, **options):
        queryset = PipelineRun.objects.order_by("run_id")
        run_id = (options.get("run_id") or "").strip()
        if run_id:
            queryset = queryset.filter(run_id=run_id)

        pipeline_runs = list(queryset)
        if run_id and not pipeline_runs:
            raise CommandError(f"Run {run_id!r} was not found.")

        updated = 0
        skipped = 0
        for pipeline_run in pipeline_runs:
            _, changed = backfill_run_browser_metadata(
                pipeline_run,
                force=bool(options.get("force")),
            )
            if changed:
                updated += 1
                self.stdout.write(self.style.SUCCESS(f"Backfilled {pipeline_run.run_id}"))
                continue

            skipped += 1
            self.stdout.write(f"Skipped {pipeline_run.run_id}")

        self.stdout.write(f"updated: {updated}")
        self.stdout.write(f"skipped: {skipped}")
