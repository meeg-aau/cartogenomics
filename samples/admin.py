from django.contrib import admin
from django.utils.html import format_html
import json

from .models import Sample


@admin.register(Sample)
class SampleAdmin(admin.ModelAdmin):
    list_display = (
        "biosample",
        "ena_sample",
        "source_dataset",
        "region",
        "locality",
        "ontology_preview",
        "latitude",
        "longitude",
        "geography_check_status",
        "geography_status_reason",
        "ingest",
        "created_at",
    )

    search_fields = (
        "biosample",
        "ena_sample",
        "region",
        "locality",
        "ontology",
    )

    list_filter = (
        "source_dataset",
        "ontology",
        "geography_check_status",
        "geography_status_reason",
        "ingest",
    )

    readonly_fields = (
        "pretty_raw_metadata",
        "created_at",
        "updated_at",
    )

    ordering = ("-created_at",)

    fields = (
        "biosample",
        "ena_sample",
        "source_dataset",
        "ingest",
        "latitude",
        "longitude",
        "region",
        "locality",
        "ontology",
        "geography_check_status",
        "geography_status_reason",
        "pretty_raw_metadata",
        "created_at",
        "updated_at",
    )

    def ontology_preview(self, obj):
        if not obj.ontology:
            return "-"
        value = str(obj.ontology)
        return value[:100] + ("..." if len(value) > 100 else "")

    ontology_preview.short_description = "Ontology"

    def pretty_raw_metadata(self, obj):
        return format_html(
            "<pre style='white-space: pre-wrap; max-width: 1000px;'>{}</pre>",
            json.dumps(obj.raw_metadata, indent=2, sort_keys=True),
        )

    pretty_raw_metadata.short_description = "Raw metadata"