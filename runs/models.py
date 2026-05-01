from django.db import models
from samples.models import Sample
from versions.models import IngestVersion


class Run(models.Model):
    """
    Represents a sequencing run (e.g. ENA/SRA run accession).
    """

    accession = models.CharField(max_length=100, unique=True)

    sample = models.ForeignKey(
        Sample,
        on_delete=models.CASCADE,
        related_name="runs",
    )

    ingest = models.ForeignKey(
        IngestVersion,
        on_delete=models.PROTECT,
        related_name="runs",
    )

    previous_ingest = models.ForeignKey(
        IngestVersion,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="previous_for_runs",
    )

    read_count = models.BigIntegerField(null=True, blank=True)
    sequencer = models.CharField(max_length=255, null=True, blank=True)
    library_source = models.CharField(max_length=100, null=True, blank=True)
    library_strategy = models.CharField(max_length=100, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.accession