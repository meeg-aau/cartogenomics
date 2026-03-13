
from django.core.exceptions import ValidationError
from django.db import models
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
        ocean_or_sea = "ocean_or_sea"
        no_coordinates = "no_coordinates"
        no_reported_country_code = "no_reported_country_code"
        reverse_geocoder_no_result = "reverse_geocoder_no_result"
        reported_cc_not_supported_by_reverse_geocoder = "reported_cc_not_supported_by_reverse_geocoder"
        match = "match"
        country_mismatch = "country_mismatch"

    class SourceDataset(models.TextChoices):
        MFD = "MFD"
        GTDB = "GTDB"
        ENA = "ENA"


    ena_sample = models.CharField(max_length=50, null=True, blank=True, unique=True, validators=[validate_ena_sample])
    biosample = models.CharField(max_length=50, null=True, blank=True, unique=True, validators=[validate_biosample])

    source_dataset = models.CharField(max_length=50, default="", choices=SourceDataset.choices)

    # link to ingest version
    ingest = models.ForeignKey(IngestVersion, on_delete=models.PROTECT, null=True, blank=True)

    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    region = models.CharField(max_length=1000, null=True, blank=True)
    locality = models.CharField(max_length=1000, null=True, blank=True)
    ontology = models.CharField(null=True, blank=True)
    geography_check_status = models.CharField(max_length=1000, null=True, blank=True, choices=GeographyCheckStatus.choices)
    geography_status_reason = models.CharField(max_length=1000, null=True, blank=True, choices=GeographyStatusReason.choices)

    raw_metadata = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.biosample or self.ena_sample or "Unnamed Sample"
