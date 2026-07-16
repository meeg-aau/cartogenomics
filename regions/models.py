from django.contrib.gis.db import models

from versions.models import IngestVersion


class CountryBoundary(models.Model):
    """
    Natural Earth country boundary polygons, used as a reference table for
    PostGIS-backed polygon/country filtering (e.g. RO-Crate export by region).
    Joined on Sample.inferred_country_code == iso_two_cc,
    or queried independently for arbitrary polygon lookups.
    """

    #   not unique: Natural Earth maps a handful of disputed/unrecognised
    #   territories to the placeholder code "-99"
    iso_two_cc = models.CharField(max_length=2, db_index=True)
    name = models.CharField(max_length=200)
    geom = models.MultiPolygonField(srid=4326)

    ingest = models.ForeignKey(
        IngestVersion,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="country_boundaries",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.iso_two_cc})"
