from django.contrib.gis import admin

from .models import CountryBoundary


@admin.register(CountryBoundary)
class CountryBoundaryAdmin(admin.GISModelAdmin):
    list_display = ("iso_two_cc", "name", "updated_at")
    search_fields = ("iso_two_cc", "name")
    ordering = ("name",)
