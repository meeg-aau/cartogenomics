from django.db import models
from samples.models import Sample
from versions.models import IngestVersion


class Run(models.Model):
    """
    Represents a sequencing run (e.g. ENA/SRA run accession).
    """

    accession = models.CharField(max_length=100)

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

    read_count = models.BigIntegerField(null=True, blank=True)

    sequencer = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Sequencing platform, e.g. Illumina NovaSeq 6000",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("accession", "ingest")

    def __str__(self):
        return self.accession