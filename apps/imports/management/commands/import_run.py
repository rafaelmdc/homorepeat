from django.core.management.base import BaseCommand, CommandError

from apps.imports.services import ImportContractError, import_published_run


class Command(BaseCommand):
    help = "Import one published HomoRepeat run from TSV + manifest artifacts."

    def add_arguments(self, parser):
        parser.add_argument(
            "--publish-root",
            required=True,
            help="Path to one published run root, for example /data/homorepeat_runs/run-001/publish",
        )
        parser.add_argument(
            "--replace-existing",
            action="store_true",
            help="Replace an existing imported run with the same run_id",
        )

    def handle(self, *args, **options):
        try:
            result = import_published_run(
                options["publish_root"],
                replace_existing=options["replace_existing"],
            )
        except ImportContractError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS(f"Imported run {result.pipeline_run.run_id}"))
        for label, count in result.counts.items():
            self.stdout.write(f"{label}: {count}")
