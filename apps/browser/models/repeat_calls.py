from django.db import models
from django.db.models import F, Q

from .base import TimestampedModel


class RunParameter(models.Model):
    class Method(models.TextChoices):
        PURE = "pure", "Pure"
        THRESHOLD = "threshold", "Threshold"
        SEED_EXTEND = "seed_extend", "Seed Extend"

    pipeline_run = models.ForeignKey(
        "PipelineRun",
        on_delete=models.CASCADE,
        related_name="run_parameters",
    )
    method = models.CharField(max_length=20, choices=Method.choices, db_index=True)
    repeat_residue = models.CharField(max_length=16, blank=True, db_index=True)
    param_name = models.CharField(max_length=255)
    param_value = models.CharField(max_length=255)

    class Meta:
        ordering = ["pipeline_run__run_id", "method", "repeat_residue", "param_name"]
        verbose_name = "imported run parameter"
        verbose_name_plural = "imported run parameters"
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
        "PipelineRun",
        on_delete=models.CASCADE,
        related_name="repeat_calls",
    )
    genome = models.ForeignKey(
        "Genome",
        on_delete=models.CASCADE,
        related_name="repeat_calls",
    )
    sequence = models.ForeignKey(
        "Sequence",
        on_delete=models.CASCADE,
        related_name="repeat_calls",
    )
    protein = models.ForeignKey(
        "Protein",
        on_delete=models.CASCADE,
        related_name="repeat_calls",
    )
    taxon = models.ForeignKey(
        "Taxon",
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
    codon_ratio_value = models.FloatField(blank=True, null=True)
    window_definition = models.CharField(max_length=255, blank=True)
    template_name = models.CharField(max_length=255, blank=True)
    merge_rule = models.CharField(max_length=255, blank=True)
    score = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["pipeline_run__run_id", "protein__protein_name", "start", "call_id"]
        verbose_name = "imported repeat-call observation"
        verbose_name_plural = "imported repeat-call observations"
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
                condition=Q(end__gte=F("start")),
                name="browser_repeatcall_end_gte_start",
            ),
        ]
        indexes = [
            models.Index(
                fields=["pipeline_run", "accession", "protein_name", "start", "id"],
                name="brw_rc_run_acc_pn_start_id",
            ),
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
