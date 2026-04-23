from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponseRedirect
from django.urls import reverse, reverse_lazy
from django.utils.decorators import method_decorator
from django.views.generic import FormView, ListView

from .forms import ImportRunForm
from .models import ImportBatch
from .services import dispatch_import_batch, enqueue_published_run


@dataclass(frozen=True)
class DetectedPublishRun:
    label: str
    run_id: str
    status: str
    finished_at_utc: str
    publish_root: str
    display_path: str


class StaffOnlyMixin:
    @method_decorator(staff_member_required)
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)


class ImportsHomeView(StaffOnlyMixin, FormView):
    template_name = "imports/home.html"
    form_class = ImportRunForm
    success_url = reverse_lazy("imports:home")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["detected_publish_runs"] = _discover_publish_runs()
        return kwargs

    def get_initial(self):
        initial = super().get_initial()
        requested_publish_root = self.request.GET.get("publish_root", "").strip()
        if not requested_publish_root:
            return initial

        detected_publish_roots = {run.publish_root for run in _discover_publish_runs()}
        if requested_publish_root in detected_publish_roots:
            initial["detected_publish_root"] = requested_publish_root
        else:
            initial["publish_root"] = requested_publish_root
        return initial

    def form_valid(self, form):
        publish_root = form.cleaned_data["resolved_publish_root"]
        replace_existing = form.cleaned_data["replace_existing"]
        manifest = _safe_read_manifest(Path(publish_root) / "metadata" / "run_manifest.json")
        queued_batch = enqueue_published_run(
            publish_root,
            replace_existing=replace_existing,
        )
        dispatch_import_batch(queued_batch)
        run_id = str(manifest.get("run_id", "")) or Path(publish_root).parent.name

        messages.success(
            self.request,
            f"Queued import batch {queued_batch.pk} for run {run_id} from {publish_root}.",
        )
        return HttpResponseRedirect(self.get_success_url())

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        recent_batches = list(ImportBatch.objects.select_related("pipeline_run")[:8])
        has_active_import_batches = _has_active_import_batches(recent_batches)
        context["detected_publish_runs"] = _discover_publish_runs()
        context["runs_root"] = str(_runs_root())
        context["recent_batches"] = recent_batches
        context["has_active_import_batches"] = has_active_import_batches
        context["enable_import_auto_refresh"] = has_active_import_batches and self.request.method == "GET"
        context["history_url"] = reverse("imports:history")
        return context


class ImportsHistoryView(StaffOnlyMixin, ListView):
    model = ImportBatch
    template_name = "imports/history.html"
    context_object_name = "import_batches"
    paginate_by = 20

    def get_queryset(self):
        return ImportBatch.objects.select_related("pipeline_run")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        has_active_import_batches = _has_active_import_batches(context["import_batches"])
        context["has_active_import_batches"] = has_active_import_batches
        context["enable_import_auto_refresh"] = has_active_import_batches
        return context


def _has_active_import_batches(import_batches) -> bool:
    active_statuses = {ImportBatch.Status.PENDING, ImportBatch.Status.RUNNING}
    return any(batch.status in active_statuses for batch in import_batches)


def _runs_root() -> Path:
    configured = getattr(settings, "HOMOREPEAT_RUNS_ROOT", None)
    if configured:
        return Path(configured)
    return Path(settings.BASE_DIR) / "runs"


def _discover_publish_runs() -> list[DetectedPublishRun]:
    runs_root = _runs_root()
    if not runs_root.exists() or not runs_root.is_dir():
        return []

    detected: list[DetectedPublishRun] = []
    seen_publish_roots: set[str] = set()
    repo_root = Path(settings.BASE_DIR).parent

    for candidate in sorted(runs_root.iterdir(), key=_publish_run_sort_key):
        publish_root = candidate / "publish"
        manifest_path = publish_root / "metadata" / "run_manifest.json"
        if not publish_root.is_dir() or not manifest_path.is_file():
            continue

        resolved_publish_root = str(publish_root.resolve())
        if resolved_publish_root in seen_publish_roots:
            continue
        seen_publish_roots.add(resolved_publish_root)

        manifest = _safe_read_manifest(manifest_path)
        display_path = resolved_publish_root
        try:
            display_path = str(Path(resolved_publish_root).relative_to(repo_root))
        except ValueError:
            pass

        detected.append(
            DetectedPublishRun(
                label=candidate.name,
                run_id=str(manifest.get("run_id", candidate.name)),
                status=str(manifest.get("status", "")),
                finished_at_utc=str(manifest.get("finished_at_utc", "")),
                publish_root=resolved_publish_root,
                display_path=display_path,
            )
        )

    return detected


def _safe_read_manifest(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


def _publish_run_sort_key(path: Path) -> tuple[int, str]:
    return (0 if path.name == "latest" else 1, path.name)
