from django.db import models

from .base import TimestampedModel


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
    canonical_sync_batch = models.ForeignKey(
        "imports.ImportBatch",
        on_delete=models.SET_NULL,
        related_name="canonical_synced_runs",
        blank=True,
        null=True,
    )
    canonical_synced_at = models.DateTimeField(blank=True, null=True, db_index=True)
    imported_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-imported_at", "run_id"]

    def __str__(self):
        return self.run_id


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
