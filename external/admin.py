from django.contrib import admin

from .models import ExternalResource


@admin.register(ExternalResource)
class ExternalResourceAdmin(admin.ModelAdmin):
    list_display = (
        "accession",
        "sample",
        "source_system",
        "url",
        "ingest",
        "created_at",
    )
    search_fields = ("url",)
    list_filter = ("source_system", "ingest")
