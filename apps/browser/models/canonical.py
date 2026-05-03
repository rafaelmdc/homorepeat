from django.db import models
from django.db.models import F, Q

from .base import TimestampedModel
from .repeat_calls import RunParameter


class CanonicalGenome(TimestampedModel):
    latest_pipeline_run = models.ForeignKey(
        "PipelineRun",
        on_delete=models.PROTECT,
        related_name="canonical_genomes",
    )
    latest_import_batch = models.ForeignKey(
        "imports.ImportBatch",
        on_delete=models.PROTECT,
        related_name="canonical_genomes",
    )
    last_seen_at = models.DateTimeField(db_index=True)
    genome_id = models.CharField(max_length=255)
    source = models.CharField(max_length=64)
    accession = models.CharField(max_length=255, unique=True, db_index=True)
    genome_name = models.CharField(max_length=255, db_index=True)
    assembly_type = models.CharField(max_length=128)
    taxon = models.ForeignKey(
        "Taxon",
        on_delete=models.PROTECT,
        related_name="canonical_genomes",
    )
    assembly_level = models.CharField(max_length=128, blank=True)
    species_name = models.CharField(max_length=255, blank=True)
    analyzed_protein_count = models.PositiveIntegerField(default=0)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["accession"]
        indexes = [
            models.Index(fields=["latest_pipeline_run"], name="brw_cgenome_run_idx"),
            models.Index(fields=["genome_name"], name="brw_cgenome_name_idx"),
            models.Index(fields=["taxon"], name="brw_cgenome_tax_idx"),
        ]

    def __str__(self):
        return self.accession


class CanonicalSequence(TimestampedModel):
    latest_pipeline_run = models.ForeignKey(
        "PipelineRun",
        on_delete=models.PROTECT,
        related_name="canonical_sequences",
    )
    latest_import_batch = models.ForeignKey(
        "imports.ImportBatch",
        on_delete=models.PROTECT,
        related_name="canonical_sequences",
    )
    last_seen_at = models.DateTimeField(db_index=True)
    genome = models.ForeignKey(
        CanonicalGenome,
        on_delete=models.CASCADE,
        related_name="sequences",
    )
    taxon = models.ForeignKey(
        "Taxon",
        on_delete=models.PROTECT,
        related_name="canonical_sequences",
    )
    sequence_id = models.CharField(max_length=255)
    sequence_name = models.CharField(max_length=255, db_index=True)
    sequence_length = models.PositiveIntegerField()
    nucleotide_sequence = models.TextField(blank=True)
    gene_symbol = models.CharField(max_length=255, blank=True, db_index=True)
    transcript_id = models.CharField(max_length=255, blank=True)
    isoform_id = models.CharField(max_length=255, blank=True)
    assembly_accession = models.CharField(max_length=255, blank=True, db_index=True)
    source_record_id = models.CharField(max_length=255, blank=True)
    protein_external_id = models.CharField(max_length=255, blank=True)
    translation_table = models.CharField(max_length=32, blank=True)
    gene_group = models.CharField(max_length=255, blank=True)
    linkage_status = models.CharField(max_length=64, blank=True)
    partial_status = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ["genome__accession", "sequence_name", "sequence_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["genome", "sequence_id"],
                name="brw_cseq_unique_genome_sid",
            ),
        ]
        indexes = [
            models.Index(fields=["latest_pipeline_run"], name="brw_cseq_run_idx"),
            models.Index(
                fields=["assembly_accession", "sequence_name", "id"],
                name="brw_cseq_acc_name_id",
            ),
            models.Index(fields=["genome"], name="brw_cseq_genome_idx"),
            models.Index(fields=["taxon"], name="brw_cseq_taxon_idx"),
            models.Index(fields=["gene_symbol"], name="brw_cseq_gene_idx"),
        ]

    def __str__(self):
        return f"{self.sequence_name} [{self.genome.accession}]"


class CanonicalProtein(TimestampedModel):
    latest_pipeline_run = models.ForeignKey(
        "PipelineRun",
        on_delete=models.PROTECT,
        related_name="canonical_proteins",
    )
    latest_import_batch = models.ForeignKey(
        "imports.ImportBatch",
        on_delete=models.PROTECT,
        related_name="canonical_proteins",
    )
    last_seen_at = models.DateTimeField(db_index=True)
    genome = models.ForeignKey(
        CanonicalGenome,
        on_delete=models.CASCADE,
        related_name="proteins",
    )
    sequence = models.ForeignKey(
        CanonicalSequence,
        on_delete=models.CASCADE,
        related_name="proteins",
    )
    taxon = models.ForeignKey(
        "Taxon",
        on_delete=models.PROTECT,
        related_name="canonical_proteins",
    )
    protein_id = models.CharField(max_length=255)
    protein_name = models.CharField(max_length=255, db_index=True)
    protein_length = models.PositiveIntegerField()
    accession = models.CharField(max_length=255, blank=True, db_index=True)
    amino_acid_sequence = models.TextField(blank=True)
    gene_symbol = models.CharField(max_length=255, blank=True, db_index=True)
    translation_method = models.CharField(max_length=64, blank=True)
    translation_status = models.CharField(max_length=64, blank=True)
    assembly_accession = models.CharField(max_length=255, blank=True)
    gene_group = models.CharField(max_length=255, blank=True)
    protein_external_id = models.CharField(max_length=255, blank=True)
    repeat_call_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["genome__accession", "protein_name", "protein_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["genome", "protein_id"],
                name="brw_cprot_unique_genome_pid",
            ),
        ]
        indexes = [
            models.Index(fields=["latest_pipeline_run"], name="brw_cprot_run_idx"),
            models.Index(
                fields=["accession", "protein_name", "id"],
                name="brw_cprot_acc_name_id",
            ),
            models.Index(fields=["protein_id"], name="brw_cprot_pid_idx"),
            models.Index(fields=["genome"], name="brw_cprot_genome_idx"),
            models.Index(fields=["taxon"], name="brw_cprot_taxon_idx"),
            models.Index(fields=["gene_symbol"], name="brw_cprot_gene_idx"),
        ]

    def __str__(self):
        return f"{self.protein_name} [{self.genome.accession}]"


class CanonicalRepeatCall(TimestampedModel):
    latest_pipeline_run = models.ForeignKey(
        "PipelineRun",
        on_delete=models.PROTECT,
        related_name="canonical_repeat_calls",
    )
    latest_import_batch = models.ForeignKey(
        "imports.ImportBatch",
        on_delete=models.PROTECT,
        related_name="canonical_repeat_calls",
    )
    last_seen_at = models.DateTimeField(db_index=True)
    latest_repeat_call = models.ForeignKey(
        "RepeatCall",
        on_delete=models.SET_NULL,
        related_name="+",
        blank=True,
        null=True,
    )
    genome = models.ForeignKey(
        CanonicalGenome,
        on_delete=models.CASCADE,
        related_name="repeat_calls",
    )
    sequence = models.ForeignKey(
        CanonicalSequence,
        on_delete=models.CASCADE,
        related_name="repeat_calls",
    )
    protein = models.ForeignKey(
        CanonicalProtein,
        on_delete=models.CASCADE,
        related_name="repeat_calls",
    )
    taxon = models.ForeignKey(
        "Taxon",
        on_delete=models.PROTECT,
        related_name="canonical_repeat_calls",
    )
    source_call_id = models.CharField(max_length=255, blank=True, db_index=True)
    method = models.CharField(max_length=20, choices=RunParameter.Method.choices, db_index=True)
    accession = models.CharField(max_length=255, blank=True, db_index=True)
    gene_symbol = models.CharField(max_length=255, blank=True, db_index=True)
    protein_name = models.CharField(max_length=255, blank=True, db_index=True)
    protein_length = models.PositiveIntegerField(default=0)
    start = models.PositiveIntegerField()
    end = models.PositiveIntegerField()
    length = models.PositiveIntegerField()
    repeat_residue = models.CharField(max_length=16, db_index=True)
    repeat_count = models.PositiveIntegerField()
    non_repeat_count = models.PositiveIntegerField()
    purity = models.FloatField()
    aa_sequence = models.TextField()
    codon_sequence = models.TextField(blank=True)
    codon_metric_name = models.CharField(max_length=255, blank=True)
    codon_metric_value = models.CharField(max_length=255, blank=True)
    codon_ratio_value = models.FloatField(blank=True, null=True)
    window_definition = models.CharField(max_length=255, blank=True)
    template_name = models.CharField(max_length=255, blank=True)
    merge_rule = models.CharField(max_length=255, blank=True)
    score = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["accession", "protein_name", "start", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["protein", "sequence", "method", "repeat_residue", "start", "end"],
                name="brw_crcall_unique_scope",
            ),
            models.CheckConstraint(
                condition=Q(purity__gte=0) & Q(purity__lte=1),
                name="brw_crcall_purity_0_1",
            ),
            models.CheckConstraint(
                condition=Q(end__gte=F("start")),
                name="brw_crcall_end_gte_start",
            ),
        ]
        indexes = [
            models.Index(
                fields=["accession", "protein_name", "start", "id"],
                name="brw_crcall_acc_name_sid",
            ),
            models.Index(fields=["method"], name="brw_crcall_method_idx"),
            models.Index(fields=["repeat_residue"], name="brw_crcall_res_idx"),
            models.Index(fields=["taxon"], name="brw_crcall_taxon_idx"),
            models.Index(fields=["protein"], name="brw_crcall_protein_idx"),
            models.Index(fields=["length"], name="brw_crcall_length_idx"),
            models.Index(
                fields=["latest_pipeline_run", "taxon", "length"],
                name="brw_crcall_run_tax_len_idx",
            ),
            models.Index(
                fields=["method", "repeat_residue", "accession", "id"],
                name="brw_crcall_mra_idx",
            ),
        ]

    def __str__(self):
        return f"{self.accession}:{self.protein.protein_id}:{self.method}:{self.start}-{self.end}"


class CanonicalRepeatCallCodonUsage(TimestampedModel):
    repeat_call = models.ForeignKey(
        CanonicalRepeatCall,
        on_delete=models.CASCADE,
        related_name="codon_usages",
    )
    amino_acid = models.CharField(max_length=16, db_index=True)
    codon = models.CharField(max_length=16, db_index=True)
    codon_count = models.PositiveIntegerField()
    codon_fraction = models.FloatField()

    class Meta:
        ordering = ["repeat_call_id", "amino_acid", "codon"]
        constraints = [
            models.UniqueConstraint(
                fields=["repeat_call", "amino_acid", "codon"],
                name="brw_crccu_unique_call_aa_codon",
            ),
            models.CheckConstraint(
                condition=Q(codon_fraction__gte=0) & Q(codon_fraction__lte=1),
                name="brw_crccu_fraction_0_1",
            ),
        ]
        indexes = [
            models.Index(
                fields=["amino_acid", "codon"],
                name="brw_crccu_aa_codon_idx",
            ),
            models.Index(
                fields=["amino_acid", "repeat_call"],
                name="brw_crccu_aa_call_idx",
            ),
        ]

    def __str__(self):
        return f"{self.repeat_call.source_call_id}:{self.amino_acid}:{self.codon}"


class CanonicalCodonCompositionSummary(TimestampedModel):
    repeat_residue = models.CharField(max_length=16)
    display_rank = models.CharField(max_length=64)
    display_taxon = models.ForeignKey(
        "Taxon",
        on_delete=models.CASCADE,
        related_name="canonical_codon_composition_summaries",
    )
    display_taxon_name = models.CharField(max_length=255)
    observation_count = models.PositiveIntegerField()
    species_count = models.PositiveIntegerField()
    codon = models.CharField(max_length=16)
    codon_share = models.FloatField()

    class Meta:
        ordering = [
            "repeat_residue",
            "display_rank",
            "-observation_count",
            "display_taxon_name",
            "display_taxon_id",
            "codon",
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["repeat_residue", "display_rank", "display_taxon", "codon"],
                name="brw_cccs_unique_scope",
            ),
            models.CheckConstraint(
                condition=Q(codon_share__gte=0) & Q(codon_share__lte=1),
                name="brw_cccs_share_0_1",
            ),
        ]
        indexes = [
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
        ]

    def __str__(self):
        return (
            f"{self.repeat_residue}:{self.display_rank}:{self.display_taxon_name}:{self.codon}"
        )


class CanonicalCodonCompositionLengthSummary(TimestampedModel):
    repeat_residue = models.CharField(max_length=16)
    display_rank = models.CharField(max_length=64)
    display_taxon = models.ForeignKey(
        "Taxon",
        on_delete=models.CASCADE,
        related_name="canonical_codon_composition_length_summaries",
    )
    display_taxon_name = models.CharField(max_length=255)
    length_bin_start = models.PositiveIntegerField()
    observation_count = models.PositiveIntegerField()
    species_count = models.PositiveIntegerField()
    codon = models.CharField(max_length=16)
    codon_share = models.FloatField()

    class Meta:
        ordering = [
            "repeat_residue",
            "display_rank",
            "-observation_count",
            "display_taxon_name",
            "display_taxon_id",
            "length_bin_start",
            "codon",
        ]
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "repeat_residue",
                    "display_rank",
                    "display_taxon",
                    "length_bin_start",
                    "codon",
                ],
                name="brw_cccls_unique_scope",
            ),
            models.CheckConstraint(
                condition=Q(codon_share__gte=0) & Q(codon_share__lte=1),
                name="brw_cccls_share_0_1",
            ),
        ]
        indexes = [
            models.Index(
                fields=[
                    "repeat_residue",
                    "display_rank",
                    "observation_count",
                    "display_taxon_name",
                    "display_taxon",
                ],
                name="brw_cccls_browse_idx",
            ),
            models.Index(
                fields=[
                    "repeat_residue",
                    "display_rank",
                    "display_taxon",
                    "length_bin_start",
                ],
                name="brw_cccls_taxbin_idx",
            ),
        ]

    def __str__(self):
        return (
            f"{self.repeat_residue}:{self.display_rank}:{self.display_taxon_name}:"
            f"{self.length_bin_start}:{self.codon}"
        )
