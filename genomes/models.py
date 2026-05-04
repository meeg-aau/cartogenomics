from django.db import models
from versions.models import IngestVersion


class Genome(models.Model):
    """Represents a Metagenome Assembled Genome (MAG)."""

    class CompletenessSoftware(models.TextChoices):
        CHECKM = "checkm", "CheckM"
        CHECKM2 = "checkm2", "CheckM2"
        BUSCO = "busco", "BUSCO"

    accession = models.CharField(max_length=100, unique=True)

    ingest = models.ForeignKey(
        IngestVersion,
        on_delete=models.PROTECT,
        related_name="genomes",
    )

    completeness = models.FloatField(null=True, blank=True)
    contamination = models.FloatField(null=True, blank=True)
    completeness_software = models.CharField(max_length=50, default="", choices=CompletenessSoftware.choices)

    genome_size = models.BigIntegerField(null=True, blank=True)
    n50 = models.BigIntegerField(null=True, blank=True)

    taxonomy = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.accession


class GenomeVersion(models.Model):
    """Immutable snapshot of a Genome's curated fields at each ingest where fields changed."""

    genome = models.ForeignKey(
        Genome,
        on_delete=models.CASCADE,
        related_name="versions",
    )
    ingest = models.ForeignKey(
        IngestVersion,
        on_delete=models.PROTECT,
        related_name="genome_versions",
    )
    valid_from = models.DateTimeField()
    valid_to = models.DateTimeField(null=True, blank=True)

    completeness = models.FloatField(null=True, blank=True)
    contamination = models.FloatField(null=True, blank=True)
    completeness_software = models.CharField(max_length=50, default="")
    genome_size = models.BigIntegerField(null=True, blank=True)
    n50 = models.BigIntegerField(null=True, blank=True)
    taxonomy = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["valid_from"]

    def __str__(self):
        return f"{self.genome} @ {self.ingest}"
