from django.db import models


class ImportBatch(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    pipeline_run = models.ForeignKey(
        "browser.PipelineRun",
        on_delete=models.SET_NULL,
        related_name="import_batches",
        blank=True,
        null=True,
    )
    source_path = models.CharField(max_length=500)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    replace_existing = models.BooleanField(default=False)
    started_at = models.DateTimeField(auto_now_add=True, db_index=True)
    finished_at = models.DateTimeField(blank=True, null=True)
    success_count = models.PositiveIntegerField(default=0)
    error_count = models.PositiveIntegerField(default=0)
    phase = models.CharField(max_length=64, blank=True, db_index=True)
    heartbeat_at = models.DateTimeField(blank=True, null=True, db_index=True)
    progress_payload = models.JSONField(default=dict, blank=True)
    row_counts = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        if self.pipeline_run_id:
            return f"{self.pipeline_run.run_id} ({self.status})"
        return f"{self.source_path} ({self.status})"
