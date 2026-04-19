import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("browser", "0020_canonicalrepeatcallcodonusage_aa_call_idx"),
    ]

    operations = [
        migrations.CreateModel(
            name="CanonicalCodonCompositionSummary",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("repeat_residue", models.CharField(max_length=16)),
                ("display_rank", models.CharField(max_length=64)),
                ("display_taxon_name", models.CharField(max_length=255)),
                ("observation_count", models.PositiveIntegerField()),
                ("species_count", models.PositiveIntegerField()),
                ("codon", models.CharField(max_length=16)),
                ("codon_share", models.FloatField()),
                (
                    "display_taxon",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="canonical_codon_composition_summaries",
                        to="browser.taxon",
                    ),
                ),
            ],
            options={
                "ordering": [
                    "repeat_residue",
                    "display_rank",
                    "-observation_count",
                    "display_taxon_name",
                    "display_taxon_id",
                    "codon",
                ],
                "indexes": [
                    models.Index(
                        fields=[
                            "repeat_residue",
                            "display_rank",
                            "observation_count",
                            "display_taxon_name",
                            "display_taxon",
                        ],
                        name="brw_cccs_browse_idx",
                    ),
                    models.Index(
                        fields=["repeat_residue", "display_rank", "display_taxon"],
                        name="brw_cccs_taxon_idx",
                    ),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("repeat_residue", "display_rank", "display_taxon", "codon"),
                        name="brw_cccs_unique_scope",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("codon_share__gte", 0), ("codon_share__lte", 1)),
                        name="brw_cccs_share_0_1",
                    ),
                ],
            },
        ),
    ]
