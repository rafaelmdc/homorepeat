from django.urls import path

from .views import ImportsHistoryView, ImportsHomeView


app_name = "imports"

urlpatterns = [
    path("", ImportsHomeView.as_view(), name="home"),
    path("history/", ImportsHistoryView.as_view(), name="history"),
]
