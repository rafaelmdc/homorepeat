from django.urls import path

from .views import (
    ImportsHistoryView,
    ImportsHomeView,
    RunDeleteView,
    RunDeletionRetryView,
    UploadRunChunkView,
    UploadRunClearView,
    UploadRunCompleteView,
    UploadRunImportFormView,
    UploadRunRetryView,
    UploadRunStartView,
    UploadRunStatusView,
    UploadedRunImportView,
)


app_name = "imports"

urlpatterns = [
    path("", ImportsHomeView.as_view(), name="home"),
    path("history/", ImportsHistoryView.as_view(), name="history"),
    path("runs/<int:pk>/delete/", RunDeleteView.as_view(), name="run-delete"),
    path("jobs/<int:job_pk>/retry/", RunDeletionRetryView.as_view(), name="deletion-retry"),
    path("uploads/start/", UploadRunStartView.as_view(), name="upload-start"),
    path("uploads/<uuid:upload_id>/chunk/", UploadRunChunkView.as_view(), name="upload-chunk"),
    path("uploads/<uuid:upload_id>/complete/", UploadRunCompleteView.as_view(), name="upload-complete"),
    path("uploads/<uuid:upload_id>/status/", UploadRunStatusView.as_view(), name="upload-status"),
    path("uploads/<uuid:upload_id>/import/", UploadedRunImportView.as_view(), name="upload-import"),
    path("uploads/<uuid:upload_id>/import-form/", UploadRunImportFormView.as_view(), name="upload-import-form"),
    path("uploads/<uuid:upload_id>/retry/", UploadRunRetryView.as_view(), name="upload-retry"),
    path("uploads/<uuid:upload_id>/clear/", UploadRunClearView.as_view(), name="upload-clear"),
]
