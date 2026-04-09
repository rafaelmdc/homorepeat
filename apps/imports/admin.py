from django.contrib import admin

from .models import ImportBatch


@admin.register(ImportBatch)
class ImportBatchAdmin(admin.ModelAdmin):
    list_display = (
        "source_path",
        "pipeline_run",
        "status",
        "phase",
        "success_count",
        "started_at",
        "heartbeat_at",
        "finished_at",
    )
    search_fields = ("source_path", "pipeline_run__run_id", "status", "phase")
    list_filter = ("status", "phase", "replace_existing")
