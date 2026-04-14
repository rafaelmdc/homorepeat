from django.core.management.base import BaseCommand, CommandError

from apps.browser.merged.build import backfill_merged_summaries_for_run
from apps.browser.models import PipelineRun


LEGACY_MERGED_BACKFILL_MESSAGE = (
    "backfill_merged_summaries is a legacy merged-only workflow. "
    "Use backfill_canonical_catalog for the active operator path."
)


class Command(BaseCommand):
    help = (
        "Legacy: rebuild merged summary and occurrence rows for stage-2 cleanup/debug only. "
        "Prefer backfill_canonical_catalog."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--run-id",
            help="Only backfill one imported run by run_id.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Rebuild merged summaries even if run-scoped occurrences already exist.",
        )
        parser.add_argument(
            "--legacy-allow",
            action="store_true",
            help="Acknowledge that this merged-only command is legacy and run it anyway.",
        )

    def handle(self, *args, **options):
        if not options.get("legacy_allow"):
            raise CommandError(
                f"{LEGACY_MERGED_BACKFILL_MESSAGE} "
                "Re-run with --legacy-allow only if you explicitly need merged rows."
            )

        self.stderr.write(self.style.WARNING(LEGACY_MERGED_BACKFILL_MESSAGE))

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
            changed = backfill_merged_summaries_for_run(
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
