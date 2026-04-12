from django.db import models
from django.db.models import Q


class TimestampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class PipelineRun(TimestampedModel):
    run_id = models.CharField(max_length=255, unique=True)
    status = models.CharField(max_length=32, db_index=True)
    profile = models.CharField(max_length=64, blank=True)
    acquisition_publish_mode = models.CharField(max_length=16, blank=True, db_index=True)
    git_revision = models.CharField(max_length=64, blank=True)
    started_at_utc = models.DateTimeField(blank=True, null=True)
    finished_at_utc = models.DateTimeField(blank=True, null=True)
    manifest_path = models.CharField(max_length=500, blank=True)
    publish_root = models.CharField(max_length=500, blank=True)
    manifest_payload = models.JSONField(default=dict, blank=True)
    browser_metadata = models.JSONField(default=dict, blank=True)
    imported_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-imported_at", "run_id"]

    def __str__(self):
        return self.run_id


class Taxon(TimestampedModel):
    taxon_id = models.PositiveBigIntegerField(unique=True)
    taxon_name = models.CharField(max_length=255, db_index=True)
    rank = models.CharField(max_length=64, blank=True, db_index=True)
    parent_taxon = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        related_name="children",
        blank=True,
        null=True,
    )
    source = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["taxon_name", "taxon_id"]
        indexes = [
            models.Index(fields=["rank", "taxon_name"], name="browser_taxon_rank_name_idx"),
        ]

    def __str__(self):
        return f"{self.taxon_name} ({self.taxon_id})"


class TaxonClosure(models.Model):
    ancestor = models.ForeignKey(
        Taxon,
        on_delete=models.CASCADE,
        related_name="closure_descendants",
    )
    descendant = models.ForeignKey(
        Taxon,
        on_delete=models.CASCADE,
        related_name="closure_ancestors",
    )
    depth = models.PositiveIntegerField()

    class Meta:
        ordering = ["ancestor__taxon_name", "depth", "descendant__taxon_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["ancestor", "descendant"],
                name="browser_taxon_closure_unique_ancestor_descendant",
            ),
            models.CheckConstraint(
                condition=Q(depth__gte=0),
                name="browser_taxon_closure_depth_gte_zero",
            ),
        ]
        indexes = [
            models.Index(
                fields=["ancestor", "depth", "descendant"],
                name="browser_taxon_closure_anc_idx",
            ),
            models.Index(
                fields=["descendant", "depth", "ancestor"],
                name="browser_taxon_closure_desc_idx",
            ),
        ]

    def __str__(self):
        return f"{self.ancestor} -> {self.descendant} ({self.depth})"


class Genome(TimestampedModel):
    pipeline_run = models.ForeignKey(
        PipelineRun,
        on_delete=models.CASCADE,
        related_name="genomes",
    )
    batch = models.ForeignKey(
        "AcquisitionBatch",
        on_delete=models.PROTECT,
        related_name="genomes",
        blank=True,
        null=True,
    )
    genome_id = models.CharField(max_length=255)
    source = models.CharField(max_length=64)
    accession = models.CharField(max_length=255, db_index=True)
    genome_name = models.CharField(max_length=255, db_index=True)
    assembly_type = models.CharField(max_length=128)
    taxon = models.ForeignKey(
        Taxon,
        on_delete=models.PROTECT,
        related_name="genomes",
    )
    assembly_level = models.CharField(max_length=128, blank=True)
    species_name = models.CharField(max_length=255, blank=True)
    analyzed_protein_count = models.PositiveIntegerField(default=0)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["pipeline_run__run_id", "accession", "genome_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["pipeline_run", "genome_id"],
                name="browser_genome_unique_run_genome_id",
            ),
        ]
        indexes = [
            models.Index(
                fields=["pipeline_run", "accession"],
                name="brw_genome_run_acc_idx",
            ),
            models.Index(
                fields=["pipeline_run", "genome_name"],
                name="brw_genome_run_name_idx",
            ),
            models.Index(
                fields=["pipeline_run", "taxon"],
                name="brw_genome_run_tax_idx",
            ),
        ]

    def __str__(self):
        return f"{self.accession} [{self.pipeline_run.run_id}]"


class Sequence(TimestampedModel):
    pipeline_run = models.ForeignKey(
        PipelineRun,
        on_delete=models.CASCADE,
        related_name="sequences",
    )
    genome = models.ForeignKey(
        Genome,
        on_delete=models.CASCADE,
        related_name="sequences",
    )
    taxon = models.ForeignKey(
        Taxon,
        on_delete=models.PROTECT,
        related_name="sequences",
    )
    sequence_id = models.CharField(max_length=255)
    sequence_name = models.CharField(max_length=255, db_index=True)
    sequence_length = models.PositiveIntegerField()
    nucleotide_sequence = models.TextField(blank=True)
    gene_symbol = models.CharField(max_length=255, blank=True, db_index=True)
    transcript_id = models.CharField(max_length=255, blank=True)
    isoform_id = models.CharField(max_length=255, blank=True)
    assembly_accession = models.CharField(max_length=255, blank=True)
    source_record_id = models.CharField(max_length=255, blank=True)
    protein_external_id = models.CharField(max_length=255, blank=True)
    translation_table = models.CharField(max_length=32, blank=True)
    gene_group = models.CharField(max_length=255, blank=True)
    linkage_status = models.CharField(max_length=64, blank=True)
    partial_status = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ["pipeline_run__run_id", "sequence_name", "sequence_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["pipeline_run", "sequence_id"],
                name="browser_sequence_unique_run_sequence_id",
            ),
        ]
        indexes = [
            models.Index(
                fields=["pipeline_run", "genome"],
                name="brw_seq_run_genome_idx",
            ),
            models.Index(
                fields=["pipeline_run", "taxon"],
                name="brw_seq_run_taxon_idx",
            ),
            models.Index(
                fields=["pipeline_run", "gene_symbol"],
                name="brw_seq_run_gene_idx",
            ),
        ]

    def __str__(self):
        return f"{self.sequence_name} [{self.pipeline_run.run_id}]"


class Protein(TimestampedModel):
    pipeline_run = models.ForeignKey(
        PipelineRun,
        on_delete=models.CASCADE,
        related_name="proteins",
    )
    genome = models.ForeignKey(
        Genome,
        on_delete=models.CASCADE,
        related_name="proteins",
    )
    sequence = models.ForeignKey(
        Sequence,
        on_delete=models.CASCADE,
        related_name="proteins",
    )
    taxon = models.ForeignKey(
        Taxon,
        on_delete=models.PROTECT,
        related_name="proteins",
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
        ordering = ["pipeline_run__run_id", "protein_name", "protein_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["pipeline_run", "protein_id"],
                name="browser_protein_unique_run_protein_id",
            ),
        ]
        indexes = [
            models.Index(
                fields=["pipeline_run", "genome"],
                name="brw_protein_run_genome_idx",
            ),
            models.Index(
                fields=["pipeline_run", "accession"],
                name="brw_protein_run_acc_idx",
            ),
            models.Index(
                fields=["pipeline_run", "taxon"],
                name="brw_protein_run_taxon_idx",
            ),
            models.Index(
                fields=["pipeline_run", "gene_symbol"],
                name="brw_protein_run_gene_idx",
            ),
        ]

    def __str__(self):
        return f"{self.protein_name} [{self.pipeline_run.run_id}]"


class RunParameter(models.Model):
    class Method(models.TextChoices):
        PURE = "pure", "Pure"
        THRESHOLD = "threshold", "Threshold"
        SEED_EXTEND = "seed_extend", "Seed Extend"

    pipeline_run = models.ForeignKey(
        PipelineRun,
        on_delete=models.CASCADE,
        related_name="run_parameters",
    )
    method = models.CharField(max_length=20, choices=Method.choices, db_index=True)
    repeat_residue = models.CharField(max_length=16, blank=True, db_index=True)
    param_name = models.CharField(max_length=255)
    param_value = models.CharField(max_length=255)

    class Meta:
        ordering = ["pipeline_run__run_id", "method", "repeat_residue", "param_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["pipeline_run", "method", "repeat_residue", "param_name"],
                name="browser_runparam_unique_run_method_residue_name",
            ),
        ]

    def __str__(self):
        residue = f"[{self.repeat_residue}]" if self.repeat_residue else ""
        return f"{self.pipeline_run.run_id}: {self.method}{residue}.{self.param_name}"


class RepeatCall(TimestampedModel):
    class Method(models.TextChoices):
        PURE = "pure", "Pure"
        THRESHOLD = "threshold", "Threshold"
        SEED_EXTEND = "seed_extend", "Seed Extend"

    pipeline_run = models.ForeignKey(
        PipelineRun,
        on_delete=models.CASCADE,
        related_name="repeat_calls",
    )
    genome = models.ForeignKey(
        Genome,
        on_delete=models.CASCADE,
        related_name="repeat_calls",
    )
    sequence = models.ForeignKey(
        Sequence,
        on_delete=models.CASCADE,
        related_name="repeat_calls",
    )
    protein = models.ForeignKey(
        Protein,
        on_delete=models.CASCADE,
        related_name="repeat_calls",
    )
    taxon = models.ForeignKey(
        Taxon,
        on_delete=models.PROTECT,
        related_name="repeat_calls",
    )
    call_id = models.CharField(max_length=255)
    method = models.CharField(max_length=20, choices=Method.choices, db_index=True)
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
    window_definition = models.CharField(max_length=255, blank=True)
    template_name = models.CharField(max_length=255, blank=True)
    merge_rule = models.CharField(max_length=255, blank=True)
    score = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["pipeline_run__run_id", "protein__protein_name", "start", "call_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["pipeline_run", "call_id"],
                name="browser_repeatcall_unique_run_call_id",
            ),
            models.CheckConstraint(
                condition=Q(purity__gte=0) & Q(purity__lte=1),
                name="browser_repeatcall_purity_between_zero_one",
            ),
            models.CheckConstraint(
                condition=Q(end__gte=models.F("start")),
                name="browser_repeatcall_end_gte_start",
            ),
        ]
        indexes = [
            models.Index(
                fields=["pipeline_run", "method"],
                name="brw_rcall_run_method_idx",
            ),
            models.Index(
                fields=["pipeline_run", "accession"],
                name="brw_rcall_run_acc_idx",
            ),
            models.Index(
                fields=["pipeline_run", "repeat_residue"],
                name="brw_rcall_run_residue_idx",
            ),
            models.Index(
                fields=["pipeline_run", "taxon"],
                name="brw_rcall_run_taxon_idx",
            ),
            models.Index(
                fields=["pipeline_run", "protein"],
                name="brw_rcall_run_protein_idx",
            ),
            models.Index(
                fields=["pipeline_run", "length"],
                name="brw_rcall_run_length_idx",
            ),
        ]

    def __str__(self):
        return f"{self.call_id} [{self.pipeline_run.run_id}]"


class AcquisitionBatch(TimestampedModel):
    pipeline_run = models.ForeignKey(
        PipelineRun,
        on_delete=models.CASCADE,
        related_name="acquisition_batches",
    )
    batch_id = models.CharField(max_length=255)

    class Meta:
        ordering = ["pipeline_run__run_id", "batch_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["pipeline_run", "batch_id"],
                name="browser_acqbatch_unique_run_batch_id",
            ),
        ]

    def __str__(self):
        return f"{self.pipeline_run.run_id}:{self.batch_id}"


class DownloadManifestEntry(TimestampedModel):
    pipeline_run = models.ForeignKey(
        PipelineRun,
        on_delete=models.CASCADE,
        related_name="download_manifest_entries",
    )
    batch = models.ForeignKey(
        AcquisitionBatch,
        on_delete=models.PROTECT,
        related_name="download_manifest_entries",
    )
    assembly_accession = models.CharField(max_length=255, db_index=True)
    download_status = models.CharField(max_length=64, blank=True, db_index=True)
    package_mode = models.CharField(max_length=64, blank=True)
    download_path = models.CharField(max_length=500, blank=True)
    rehydrated_path = models.CharField(max_length=500, blank=True)
    checksum = models.CharField(max_length=255, blank=True)
    file_size_bytes = models.PositiveBigIntegerField(blank=True, null=True)
    download_started_at = models.DateTimeField(blank=True, null=True)
    download_finished_at = models.DateTimeField(blank=True, null=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["pipeline_run__run_id", "batch__batch_id", "assembly_accession"]
        constraints = [
            models.UniqueConstraint(
                fields=["pipeline_run", "batch", "assembly_accession"],
                name="browser_dlmfest_unique_run_batch_accession",
            ),
        ]
        indexes = [
            models.Index(
                fields=["pipeline_run", "batch"],
                name="brw_dlmfest_run_batch_idx",
            ),
            models.Index(
                fields=["pipeline_run", "download_status"],
                name="brw_dlmfest_run_status_idx",
            ),
        ]

    def __str__(self):
        return f"{self.assembly_accession} [{self.batch.batch_id}]"


class NormalizationWarning(TimestampedModel):
    pipeline_run = models.ForeignKey(
        PipelineRun,
        on_delete=models.CASCADE,
        related_name="normalization_warnings",
    )
    batch = models.ForeignKey(
        AcquisitionBatch,
        on_delete=models.PROTECT,
        related_name="normalization_warnings",
    )
    warning_code = models.CharField(max_length=255, db_index=True)
    warning_scope = models.CharField(max_length=64, blank=True, db_index=True)
    warning_message = models.TextField(blank=True)
    genome_id = models.CharField(max_length=255, blank=True, db_index=True)
    sequence_id = models.CharField(max_length=255, blank=True, db_index=True)
    protein_id = models.CharField(max_length=255, blank=True, db_index=True)
    assembly_accession = models.CharField(max_length=255, blank=True, db_index=True)
    source_file = models.CharField(max_length=500, blank=True)
    source_record_id = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["pipeline_run__run_id", "batch__batch_id", "warning_code", "assembly_accession"]
        indexes = [
            models.Index(
                fields=["pipeline_run", "batch"],
                name="brw_normwarn_run_batch_idx",
            ),
            models.Index(
                fields=["pipeline_run", "assembly_accession"],
                name="brw_normwarn_run_acc_idx",
            ),
            models.Index(
                fields=["pipeline_run", "warning_code", "warning_scope"],
                name="brw_normwarn_run_code_idx",
            ),
        ]

    def __str__(self):
        return f"{self.warning_code} [{self.batch.batch_id}]"


class AccessionStatus(TimestampedModel):
    pipeline_run = models.ForeignKey(
        PipelineRun,
        on_delete=models.CASCADE,
        related_name="accession_status_rows",
    )
    batch = models.ForeignKey(
        AcquisitionBatch,
        on_delete=models.PROTECT,
        related_name="accession_status_rows",
        blank=True,
        null=True,
    )
    assembly_accession = models.CharField(max_length=255, db_index=True)
    download_status = models.CharField(max_length=64, blank=True)
    normalize_status = models.CharField(max_length=64, blank=True)
    translate_status = models.CharField(max_length=64, blank=True)
    detect_status = models.CharField(max_length=64, blank=True)
    finalize_status = models.CharField(max_length=64, blank=True)
    terminal_status = models.CharField(max_length=64, blank=True, db_index=True)
    failure_stage = models.CharField(max_length=255, blank=True)
    failure_reason = models.TextField(blank=True)
    n_genomes = models.PositiveIntegerField(default=0)
    n_proteins = models.PositiveIntegerField(default=0)
    n_repeat_calls = models.PositiveIntegerField(default=0)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["pipeline_run__run_id", "assembly_accession"]
        constraints = [
            models.UniqueConstraint(
                fields=["pipeline_run", "assembly_accession"],
                name="browser_accstatus_unique_run_accession",
            ),
        ]
        indexes = [
            models.Index(
                fields=["pipeline_run", "terminal_status"],
                name="brw_accstatus_run_terminal_idx",
            ),
        ]

    def __str__(self):
        return f"{self.assembly_accession} [{self.pipeline_run.run_id}]"


class AccessionCallCount(TimestampedModel):
    pipeline_run = models.ForeignKey(
        PipelineRun,
        on_delete=models.CASCADE,
        related_name="accession_call_count_rows",
    )
    batch = models.ForeignKey(
        AcquisitionBatch,
        on_delete=models.PROTECT,
        related_name="accession_call_count_rows",
        blank=True,
        null=True,
    )
    assembly_accession = models.CharField(max_length=255, db_index=True)
    method = models.CharField(max_length=20, choices=RunParameter.Method.choices, db_index=True)
    repeat_residue = models.CharField(max_length=16, blank=True, db_index=True)
    detect_status = models.CharField(max_length=64, blank=True)
    finalize_status = models.CharField(max_length=64, blank=True)
    n_repeat_calls = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["pipeline_run__run_id", "assembly_accession", "method", "repeat_residue"]
        constraints = [
            models.UniqueConstraint(
                fields=["pipeline_run", "assembly_accession", "method", "repeat_residue"],
                name="browser_acccallcount_unique_run_accession_method_residue",
            ),
        ]
        indexes = [
            models.Index(
                fields=["pipeline_run", "method", "repeat_residue"],
                name="brw_acccall_run_method_res_idx",
            ),
        ]

    def __str__(self):
        return f"{self.assembly_accession} [{self.method}:{self.repeat_residue}]"
