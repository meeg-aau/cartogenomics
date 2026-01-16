from django.db import models

# Create your models here.
from django.db import models


class Version(models.Model):
    """
    Represents a dataset or ingestion version.
    Examples:
      - source="MFD", label="mfd_2026_01_15"
      - source="GTDB", label="R220"
    """
    source = models.CharField(max_length=50)
    label = models.CharField(max_length=100)

    retrieved_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("source", "label")

    def __str__(self):
        return f"{self.source}:{self.label}"
