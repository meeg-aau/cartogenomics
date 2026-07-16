from django.contrib import admin

from .models import CartogenomicsRelease, IngestVersion


@admin.register(IngestVersion)
class IngestVersionAdmin(admin.ModelAdmin):
    list_display = ("label", "source_system", "data_type", "ingested_on")
    search_fields = ("label", "notes")


@admin.register(CartogenomicsRelease)
class CartogenomicsReleaseAdmin(admin.ModelAdmin):
    list_display = ("label", "created_at")
    search_fields = ("label",)
