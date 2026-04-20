from django.core.management.base import BaseCommand

from apps.browser.stats.codon_rollups import rebuild_canonical_codon_composition_summaries


class Command(BaseCommand):
    help = "Rebuild current-catalog codon composition summary rows from canonical browser tables."

    def handle(self, *args, **options):
        row_count = rebuild_canonical_codon_composition_summaries()
        self.stdout.write(self.style.SUCCESS("Rebuilt codon composition summaries"))
        self.stdout.write(f"rows: {row_count}")
