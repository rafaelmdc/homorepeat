from django.urls import path

from .views import (
    ImportsHistoryView,
    ImportsHomeView,
    UploadRunChunkView,
    UploadRunCompleteView,
    UploadRunStartView,
    UploadedRunImportView,
)


app_name = "imports"

urlpatterns = [
    path("", ImportsHomeView.as_view(), name="home"),
    path("history/", ImportsHistoryView.as_view(), name="history"),
    path("uploads/start/", UploadRunStartView.as_view(), name="upload-start"),
    path("uploads/<uuid:upload_id>/chunk/", UploadRunChunkView.as_view(), name="upload-chunk"),
    path("uploads/<uuid:upload_id>/complete/", UploadRunCompleteView.as_view(), name="upload-complete"),
    path("uploads/<uuid:upload_id>/import/", UploadedRunImportView.as_view(), name="upload-import"),
]
