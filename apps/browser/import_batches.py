from django.db.models import Q

from apps.imports.models import ImportBatch

from .models import PipelineRun


def latest_completed_import_batch_for_run(pipeline_run: PipelineRun) -> ImportBatch | None:
    filters = Q(pipeline_run=pipeline_run)
    if pipeline_run.publish_root:
        filters |= Q(source_path=pipeline_run.publish_root)
    return (
        ImportBatch.objects.filter(filters, status=ImportBatch.Status.COMPLETED)
        .order_by("-finished_at", "-started_at", "-pk")
        .first()
    )
