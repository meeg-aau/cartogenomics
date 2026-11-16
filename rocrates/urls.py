from django.urls import path

from rocrates.views import DownloadView, ExportView, StatusView

urlpatterns = [
    path("", ExportView.as_view(), name="rocrate_export"),
    path("<uuid:job_id>/", StatusView.as_view(), name="rocrate_status"),
    path("<uuid:job_id>/download/", DownloadView.as_view(), name="rocrate_download"),
]
