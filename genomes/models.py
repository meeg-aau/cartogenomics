from django.db import models
from versions.models import IngestVersion


class Genome(models.Model):
    """
    Represents a Metagenome Assembled Genome (MAG).
    """

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

    previous_ingest = models.ForeignKey(
        IngestVersion,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="previous_for_genomes",
    )

    # Quality metrics
    completeness = models.FloatField(null=True, blank=True)
    contamination = models.FloatField(null=True, blank=True)
    completeness_software = models.CharField(max_length=50, default="", choices=CompletenessSoftware.choices)

    genome_size = models.BigIntegerField(null=True, blank=True)
    n50 = models.BigIntegerField(null=True, blank=True)

    taxonomy = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        pass

    def __str__(self):
        return self.accession
