
from django.db import models
from versions.models import Version


class Sample(models.Model):
    biosample_accession = models.CharField(max_length=50, unique=True)

    # which dataset this sample came from (e.g. "MFD", "GTDB", "ENA")
    source_dataset = models.CharField(max_length=50, default="")

    # link to Version
    version = models.ForeignKey(Version, on_delete=models.PROTECT, null=True, blank=True)

    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    location = models.CharField(max_length=1000, null=True, blank=True)

    raw_metadata = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.biosample_accession
