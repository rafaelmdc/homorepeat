from __future__ import annotations

import ipaddress
import json
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse, reverse_lazy
from django.utils.decorators import method_decorator
from django.views import View
from django.views.generic import FormView, ListView

from apps.browser.models import PipelineRun
from apps.imports.services.deletion.jobs import queue_deletion, retry_deletion
from apps.imports.services.deletion.planning import build_deletion_plan
from apps.imports.services.deletion.safety import DeletionTargetError, validate_deletion_target

from .forms import ImportRunForm
from .models import DeletionJob, ImportBatch, UploadedRun
from .policy import UploadPolicyError, check_active_upload_limit, check_daily_bytes_limit, check_zip_size_limit
from .services import dispatch_import_batch, enqueue_published_run
from .services.uploads import (
    UploadValidationError,
    clear_upload_working_files,
    complete_upload,
    get_upload_status,
    queue_uploaded_run_import,
    retry_upload_extraction,
    start_upload,
    store_chunk,
)


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
        has_active_uploaded_runs = _has_active_uploaded_runs()
        context["detected_publish_runs"] = _discover_publish_runs()
        context["runs_root"] = str(_runs_root())
        context["recent_batches"] = recent_batches
        context["uploaded_runs"] = UploadedRun.objects.select_related("import_batch").order_by("-created_at")[:10]
        context["has_active_import_batches"] = has_active_import_batches
        context["has_active_uploaded_runs"] = has_active_uploaded_runs
        context["enable_import_auto_refresh"] = (
            has_active_import_batches or has_active_uploaded_runs
        ) and self.request.method == "GET"
        context["history_url"] = reverse("imports:history")
        context["upload_start_url"] = reverse("imports:upload-start")
        context["upload_chunk_url_template"] = _upload_url_template("imports:upload-chunk")
        context["upload_complete_url_template"] = _upload_url_template("imports:upload-complete")
        context["upload_status_url_template"] = _upload_url_template("imports:upload-status")
        context["upload_chunk_size_bytes"] = settings.HOMOREPEAT_UPLOAD_CHUNK_BYTES
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


class UploadRunStartView(StaffOnlyMixin, View):
    http_method_names = ["post"]

    def post(self, request):
        try:
            payload = json.loads(request.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _json_error("Request body must be valid JSON.")

        try:
            size_bytes = int(payload.get("size_bytes", 0))
            check_active_upload_limit(request.user)
            check_daily_bytes_limit(request.user, size_bytes)
            check_zip_size_limit(request.user, size_bytes)
            file_sha256 = payload.get("file_sha256")
            uploaded_run = start_upload(
                filename=str(payload.get("filename", "")),
                size_bytes=size_bytes,
                total_chunks=int(payload.get("total_chunks", 0)),
                file_sha256=str(file_sha256) if file_sha256 is not None else None,
                created_by=_database_user(request),
                actor_label=_actor_label(request),
                client_ip=_get_client_ip(request),
                user_agent=(request.META.get("HTTP_USER_AGENT", "") or "")[:500] or None,
            )
        except UploadPolicyError as exc:
            return _json_error(str(exc), status=429)
        except (TypeError, ValueError, UploadValidationError) as exc:
            return _json_error(str(exc))

        return JsonResponse(
            {
                "ok": True,
                "upload_id": str(uploaded_run.upload_id),
                "chunk_size_bytes": uploaded_run.chunk_size_bytes,
                "received_chunks": uploaded_run.received_chunks,
                "status": uploaded_run.status,
            }
        )


class UploadRunChunkView(StaffOnlyMixin, View):
    http_method_names = ["post"]

    def post(self, request, upload_id):
        try:
            chunk_index = int(request.POST.get("chunk_index", ""))
        except ValueError:
            return _json_error("chunk_index must be an integer.")

        chunk = request.FILES.get("chunk")
        if chunk is None:
            return _json_error("Missing uploaded chunk file.")

        chunk_sha256 = request.POST.get("chunk_sha256") or None
        try:
            uploaded_run = store_chunk(
                upload_id=upload_id,
                chunk_index=chunk_index,
                chunk=chunk,
                chunk_sha256=chunk_sha256,
            )
        except UploadedRun.DoesNotExist:
            return _json_error("Upload was not found.", status=404)
        except UploadValidationError as exc:
            return _json_error(str(exc))

        return JsonResponse(
            {
                "ok": True,
                "upload_id": str(uploaded_run.upload_id),
                "received_chunks": uploaded_run.received_chunks,
                "received_count": len(uploaded_run.received_chunks),
                "total_chunks": uploaded_run.total_chunks,
                "received_bytes": uploaded_run.received_bytes,
                "status": uploaded_run.status,
            }
        )


class UploadRunCompleteView(StaffOnlyMixin, View):
    http_method_names = ["post"]

    def post(self, request, upload_id):
        try:
            completed_upload = complete_upload(
                upload_id=upload_id,
                completed_by=_database_user(request),
            )
        except UploadedRun.DoesNotExist:
            return _json_error("Upload was not found.", status=404)
        except UploadValidationError as exc:
            return _json_error(str(exc))

        uploaded_run = completed_upload.uploaded_run
        if completed_upload.completed_now:
            from apps.imports.tasks import extract_uploaded_run

            extract_uploaded_run.delay(uploaded_run.pk)

        return JsonResponse(
            {
                "ok": True,
                "upload_id": str(uploaded_run.upload_id),
                "received_chunks": uploaded_run.received_chunks,
                "received_count": len(uploaded_run.received_chunks),
                "total_chunks": uploaded_run.total_chunks,
                "received_bytes": uploaded_run.received_bytes,
                "status": uploaded_run.status,
            }
        )


class UploadedRunImportView(StaffOnlyMixin, View):
    http_method_names = ["post"]

    def post(self, request, upload_id):
        try:
            queued_import = queue_uploaded_run_import(
                upload_id=upload_id,
                replace_existing=_request_bool(request, "replace_existing"),
                import_requested_by=_database_user(request),
            )
        except UploadedRun.DoesNotExist:
            return _json_error("Upload was not found.", status=404)
        except UploadValidationError as exc:
            return _json_error(str(exc))

        uploaded_run = queued_import.uploaded_run
        import_batch = queued_import.import_batch
        return JsonResponse(
            {
                "ok": True,
                "upload_id": str(uploaded_run.upload_id),
                "status": uploaded_run.status,
                "queued_now": queued_import.queued_now,
                "import_batch": {
                    "id": import_batch.pk,
                    "status": import_batch.status,
                    "phase": import_batch.phase,
                    "celery_task_id": import_batch.celery_task_id,
                },
            }
        )


class UploadRunStatusView(StaffOnlyMixin, View):
    http_method_names = ["get"]

    def get(self, request, upload_id):
        try:
            payload = get_upload_status(upload_id=upload_id)
        except UploadedRun.DoesNotExist:
            return _json_error("Upload was not found.", status=404)
        return JsonResponse(payload)


class UploadRunImportFormView(StaffOnlyMixin, View):
    http_method_names = ["post"]

    def post(self, request, upload_id):
        try:
            queued_import = queue_uploaded_run_import(
                upload_id=upload_id,
                replace_existing=_request_bool(request, "replace_existing"),
                import_requested_by=request.user if request.user.is_authenticated else None,
            )
        except UploadedRun.DoesNotExist:
            messages.error(request, "Upload was not found.")
        except UploadValidationError as exc:
            messages.error(request, str(exc))
        else:
            run = queued_import.uploaded_run
            label = run.run_id or run.original_filename
            messages.success(request, f"Import queued for {label}.")
        return HttpResponseRedirect(reverse("imports:home"))


class UploadRunRetryView(StaffOnlyMixin, View):
    http_method_names = ["post"]

    def post(self, request, upload_id):
        try:
            retry_upload_extraction(upload_id=upload_id)
        except UploadedRun.DoesNotExist:
            messages.error(request, "Upload was not found.")
        except UploadValidationError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Extraction re-queued.")
        return HttpResponseRedirect(reverse("imports:home"))


class UploadRunClearView(StaffOnlyMixin, View):
    http_method_names = ["post"]

    def post(self, request, upload_id):
        try:
            clear_upload_working_files(upload_id=upload_id)
        except UploadedRun.DoesNotExist:
            messages.error(request, "Upload was not found.")
        except UploadValidationError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Working files cleared.")
        return HttpResponseRedirect(reverse("imports:home"))


class RunDeleteView(StaffOnlyMixin, View):
    """GET shows the impact plan; POST (with confirm) queues the deletion job."""

    http_method_names = ["get", "post"]

    def get(self, request, pk):
        run = get_object_or_404(PipelineRun, pk=pk)
        try:
            validate_deletion_target(run)
        except DeletionTargetError as exc:
            messages.error(request, str(exc))
            return HttpResponseRedirect(reverse("browser:run-detail", kwargs={"pk": pk}))
        plan = build_deletion_plan(run)
        return render(request, "imports/run_delete_confirm.html", {
            "pipeline_run": run,
            "plan": plan,
        })

    def post(self, request, pk):
        run = get_object_or_404(PipelineRun, pk=pk)
        if not request.POST.get("confirm"):
            messages.error(request, "Check the confirmation box to proceed with deletion.")
            return HttpResponseRedirect(reverse("imports:run-delete", kwargs={"pk": pk}))

        existing_active_job_pk = (
            DeletionJob.objects.filter(
                pipeline_run=run,
                status__in=[DeletionJob.Status.PENDING, DeletionJob.Status.RUNNING],
            )
            .values_list("pk", flat=True)
            .first()
        )

        try:
            job = queue_deletion(
                run,
                reason=request.POST.get("reason", "").strip(),
                requested_by=_database_user(request),
                requested_by_label=_actor_label(request),
            )
        except DeletionTargetError as exc:
            messages.error(request, str(exc))
        else:
            if existing_active_job_pk == job.pk:
                messages.warning(
                    request,
                    f"An active deletion job (id={job.pk}) already exists for this run.",
                )
            else:
                messages.success(
                    request,
                    f"Deletion queued (job id={job.pk}). The run will be removed in the background.",
                )
        return HttpResponseRedirect(reverse("browser:run-detail", kwargs={"pk": pk}))


class RunDeletionRetryView(StaffOnlyMixin, View):
    """POST retries a failed DeletionJob and redirects back to the run detail page."""

    http_method_names = ["post"]

    def post(self, request, job_pk):
        job = get_object_or_404(DeletionJob.objects.select_related("pipeline_run"), pk=job_pk)
        run_pk = job.pipeline_run_id
        try:
            retry_deletion(job)
        except DeletionTargetError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, f"Deletion job {job.pk} re-queued.")
        if run_pk:
            return HttpResponseRedirect(reverse("browser:run-detail", kwargs={"pk": run_pk}))
        return HttpResponseRedirect(reverse("imports:home"))


def _request_bool(request, key: str) -> bool:
    value = request.POST.get(key, "")
    return str(value).lower() in {"1", "true", "yes", "on"}


def _get_client_ip(request) -> str | None:
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded_for and getattr(settings, "HOMOREPEAT_TRUST_X_FORWARDED_FOR", False):
        forwarded_addr = _clean_ip(forwarded_for.split(",")[0].strip())
        if forwarded_addr:
            return forwarded_addr
    addr = request.META.get("REMOTE_ADDR")
    return _clean_ip(addr)


def _clean_ip(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return str(ipaddress.ip_address(value.strip()))[:45]
    except ValueError:
        return None


def _database_user(request):
    user = getattr(request, "user", None)
    if not getattr(user, "is_authenticated", False):
        return None
    if getattr(user, "pk", None) is None:
        return None
    return user


def _actor_label(request) -> str | None:
    user = getattr(request, "user", None)
    if not getattr(user, "is_authenticated", False):
        return "anonymous"

    username = ""
    if hasattr(user, "get_username"):
        username = user.get_username()
    username = username or str(user)

    if getattr(user, "pk", None) is None:
        return f"synthetic:{username}"[:255]
    return f"user:{user.pk}:{username}"[:255]


def _json_error(message: str, *, status: int = 400) -> JsonResponse:
    return JsonResponse(
        {
            "ok": False,
            "error": message,
        },
        status=status,
    )


def _upload_url_template(route_name: str) -> str:
    placeholder_uuid = UUID("00000000-0000-0000-0000-000000000000")
    return reverse(route_name, kwargs={"upload_id": placeholder_uuid}).replace(
        str(placeholder_uuid),
        "__upload_id__",
    )


def _has_active_import_batches(import_batches) -> bool:
    active_statuses = {ImportBatch.Status.PENDING, ImportBatch.Status.RUNNING}
    return any(batch.status in active_statuses for batch in import_batches)


def _has_active_uploaded_runs() -> bool:
    active_statuses = {
        UploadedRun.Status.RECEIVING,
        UploadedRun.Status.RECEIVED,
        UploadedRun.Status.EXTRACTING,
        UploadedRun.Status.QUEUED,
    }
    return UploadedRun.objects.filter(status__in=active_statuses).exists()


def _runs_root() -> Path:
    configured = getattr(settings, "HOMOREPEAT_RUNS_ROOT", None)
    if configured:
        return Path(configured)
    return Path(settings.BASE_DIR) / "runs"


def _imports_library_root() -> Path:
    return Path(settings.HOMOREPEAT_IMPORTS_ROOT) / "library"


def _discover_publish_runs() -> list[DetectedPublishRun]:
    detected: list[DetectedPublishRun] = []
    seen_publish_roots: set[str] = set()

    for root in (_runs_root(), _imports_library_root()):
        for run in _discover_publish_runs_in(root):
            if run.publish_root in seen_publish_roots:
                continue
            detected.append(run)
            seen_publish_roots.add(run.publish_root)

    return detected


def _discover_publish_runs_in(runs_root: Path) -> list[DetectedPublishRun]:
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
