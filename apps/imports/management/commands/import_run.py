from django.core.management.base import BaseCommand, CommandError

from apps.imports.services import (
    ImportContractError,
    import_published_run,
    process_import_batch,
    process_next_pending_import_batch,
)


class Command(BaseCommand):
    help = "Import one published HomoRepeat run from TSV + manifest artifacts."

    def add_arguments(self, parser):
        parser.add_argument(
            "--publish-root",
            help="Path to one published run root, for example /data/homorepeat_runs/run-001/publish",
        )
        parser.add_argument(
            "--batch-id",
            type=int,
            help="Process one queued ImportBatch by primary key.",
        )
        parser.add_argument(
            "--next-pending",
            action="store_true",
            help="Process the oldest queued pending ImportBatch.",
        )
        parser.add_argument(
            "--replace-existing",
            action="store_true",
            help="Replace an existing imported run with the same run_id",
        )

    def handle(self, *args, **options):
        publish_root = options.get("publish_root")
        batch_id = options.get("batch_id")
        next_pending = bool(options.get("next_pending"))
        chosen_modes = sum(bool(value) for value in [publish_root, batch_id, next_pending])
        if chosen_modes != 1:
            raise CommandError("Choose exactly one of --publish-root, --batch-id, or --next-pending.")

        try:
            if publish_root:
                result = import_published_run(
                    publish_root,
                    replace_existing=options["replace_existing"],
                )
            elif batch_id is not None:
                result = process_import_batch(batch_id)
            else:
                result = process_next_pending_import_batch()
        except ImportContractError as exc:
            raise CommandError(str(exc)) from exc

        if result is None:
            self.stdout.write("No pending import batches were available.")
            return

        self.stdout.write(self.style.SUCCESS(f"Imported run {result.pipeline_run.run_id}"))
        self.stdout.write(f"batch_id: {result.batch.pk}")
        self.stdout.write(f"phase: {result.batch.phase}")
        for label, count in result.counts.items():
            self.stdout.write(f"{label}: {count}")
