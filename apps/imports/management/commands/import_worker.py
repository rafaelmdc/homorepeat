from __future__ import annotations

from time import sleep

from django.core.management.base import BaseCommand, CommandError

from apps.imports.services import ImportContractError, process_next_pending_import_batch


class Command(BaseCommand):
    help = "Run a simple database-backed import worker that processes queued ImportBatch rows."

    def add_arguments(self, parser):
        parser.add_argument(
            "--once",
            action="store_true",
            help="Process at most one pending ImportBatch and exit.",
        )
        parser.add_argument(
            "--poll-interval",
            type=float,
            default=2.0,
            help="Seconds to sleep between polls when no pending ImportBatch is available.",
        )

    def handle(self, *args, **options):
        poll_interval = float(options["poll_interval"])
        if poll_interval <= 0:
            raise CommandError("--poll-interval must be greater than zero.")

        run_once = bool(options["once"])
        if run_once:
            self._process_one_batch(raise_errors=True)
            return

        self.stdout.write(self.style.SUCCESS("Import worker started."))
        self.stdout.write(f"Polling every {poll_interval:g} seconds.")
        while True:
            processed = self._process_one_batch()
            if processed:
                continue
            sleep(poll_interval)

    def _process_one_batch(self, *, raise_errors: bool = False) -> bool:
        try:
            result = process_next_pending_import_batch()
        except ImportContractError as exc:
            if raise_errors:
                raise CommandError(str(exc)) from exc
            self.stderr.write(self.style.ERROR(str(exc)))
            return False
        except Exception as exc:
            if raise_errors:
                raise
            self.stderr.write(self.style.ERROR(f"Import batch failed: {exc}"))
            return False

        if result is None:
            self.stdout.write("No pending import batches were available.")
            return False

        self.stdout.write(self.style.SUCCESS(f"Imported run {result.pipeline_run.run_id}"))
        self.stdout.write(f"batch_id: {result.batch.pk}")
        self.stdout.write(f"phase: {result.batch.phase}")
        for label, count in result.counts.items():
            self.stdout.write(f"{label}: {count}")
        return True
