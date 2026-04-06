from django.contrib import admin

from .models import ImportBatch


@admin.register(ImportBatch)
class ImportBatchAdmin(admin.ModelAdmin):
    list_display = ("source_path", "pipeline_run", "status", "success_count", "started_at", "finished_at")
    search_fields = ("source_path", "pipeline_run__run_id", "status")
    list_filter = ("status", "replace_existing")
