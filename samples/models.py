from django.contrib.gis.db import models
from django.core.exceptions import ValidationError

from versions.models import IngestVersion


def validate_ena_sample(value):
    if value and not value.startswith(("ERS", "SRS", "DRS")):
        raise ValidationError("ena_sample must start with ERS, SRS, or DRS")


def validate_biosample(value):
    if value and not value.startswith("SAM"):
        raise ValidationError("biosample must start with SAM")


class Sample(models.Model):

    class GeographyCheckStatus(models.TextChoices):
        PASS = "PASS"
        WARN = "WARN"
        FAIL = "FAIL"
        SKIP = "SKIP"

    class GeographyStatusReason(models.TextChoices):
        #   kept in sync with sample_metadata_curation's
        #   LocationCurator.geo_consistency_check() geo_check_reason values
        ocean_or_sea = "ocean_or_sea"
        no_coordinates = "no_coordinates"
        null_island = "null_island"
        identical_lat_long = "identical_lat_long"
        coordinates_suspiciously_round = "coordinates_suspiciously_round"
        implausibly_precise = "implausibly_precise"
        centroid_or_capital = "centroid_or_capital"
        known_institution = "known_institution"
        match_territory = "match_territory"
        small_island_not_in_reference = "small_island_not_in_reference"
        no_reported_country_code = "no_reported_country_code"
        disputed_or_unrecognised_territory = "disputed_or_unrecognised_territory"
        match = "match"
        match_near_border = "match_near_border"
        country_mismatch = "country_mismatch"

    class SourceDataset(models.TextChoices):
        MFD = "MFD"
        GTDB = "GTDB"
        ENA = "ENA"

    ena_sample = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        unique=True,
        validators=[validate_ena_sample],
    )
    biosample = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        unique=True,
        validators=[validate_biosample],
    )

    source_dataset = models.CharField(
        max_length=50, default="", choices=SourceDataset.choices
    )

    ingest = models.ForeignKey(
        IngestVersion,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="samples",
    )

    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    region = models.CharField(max_length=1000, null=True, blank=True)
    locality = models.CharField(max_length=1000, null=True, blank=True)
    ontology = models.CharField(null=True, blank=True)
    location = models.PointField(null=True, blank=True, srid=4326, geography=True)
    geography_check_status = models.CharField(
        max_length=1000, null=True, blank=True, choices=GeographyCheckStatus.choices
    )
    geography_status_reason = models.CharField(
        max_length=1000, null=True, blank=True, choices=GeographyStatusReason.choices
    )
    inferred_country_code = models.CharField(max_length=2, null=True, blank=True)
    coordinates_reversed = models.BooleanField(null=True, blank=True)
    coord_precision_deg = models.FloatField(null=True, blank=True)

    raw_metadata = models.JSONField(default=dict, blank=True)

    archive_created = models.DateTimeField(null=True, blank=True)
    archive_updated = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.biosample or self.ena_sample or "Unnamed Sample"


class SampleVersion(models.Model):
    """Immutable snapshot of a Sample's curated fields at each ingest where
    fields changed."""

    sample = models.ForeignKey(
        Sample,
        on_delete=models.PROTECT,
        related_name="versions",
    )
    ingest = models.ForeignKey(
        IngestVersion,
        on_delete=models.PROTECT,
        related_name="sample_versions",
    )
    valid_from = models.DateTimeField()
    valid_to = models.DateTimeField(null=True, blank=True)

    biosample = models.CharField(max_length=50, null=True, blank=True)
    ena_sample = models.CharField(max_length=50, null=True, blank=True)
    source_dataset = models.CharField(max_length=50, default="")
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    location = models.PointField(null=True, blank=True, srid=4326, geography=True)
    region = models.CharField(max_length=1000, null=True, blank=True)
    locality = models.CharField(max_length=1000, null=True, blank=True)
    ontology = models.CharField(null=True, blank=True)
    geography_check_status = models.CharField(max_length=1000, null=True, blank=True)
    geography_status_reason = models.CharField(max_length=1000, null=True, blank=True)
    inferred_country_code = models.CharField(max_length=2, null=True, blank=True)
    coordinates_reversed = models.BooleanField(null=True, blank=True)
    coord_precision_deg = models.FloatField(null=True, blank=True)
    raw_metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["valid_from"]

    def __str__(self):
        return f"{self.sample} @ {self.ingest}"
