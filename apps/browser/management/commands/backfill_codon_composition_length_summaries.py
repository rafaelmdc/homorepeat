from django.core.management.base import BaseCommand

from apps.browser.stats.codon_length_rollups import (
    rebuild_canonical_codon_composition_length_summaries,
)


class Command(BaseCommand):
    help = "Rebuild current-catalog codon composition by length summary rows from canonical browser tables."

    def handle(self, *args, **options):
        row_count = rebuild_canonical_codon_composition_length_summaries()
        self.stdout.write(self.style.SUCCESS("Rebuilt codon composition by length summaries"))
        self.stdout.write(f"rows: {row_count}")
