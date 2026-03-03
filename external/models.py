from django.db import models
from django.db.models import CheckConstraint, Q

from versions.models import IngestVersion


class ExternalResource(models.Model):

    class SourceSystem(models.TextChoices):
        ENA = "ENA"
        BIOSAMPLES = "BIOSAMPLES"
        BIOSTUDIES = "BIOSTUDIES"
        INTERNAL = "INTERNAL"

    source_system = models.CharField(
        max_length=32,
        choices=SourceSystem.choices,
    )

    accession = models.CharField(max_length=100)

    url = models.URLField(max_length=500)

    ingest = models.ForeignKey(
        IngestVersion,
        on_delete=models.PROTECT,
        related_name="external_resources",
    )

    # Optional links
    sample = models.ForeignKey(
        "samples.Sample",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="external_resources",
    )

    run = models.ForeignKey(
        "runs.Run",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="external_resources",
    )

    genome = models.ForeignKey(
        "genomes.Genome",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="external_resources",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("source_system", "accession", "ingest")
        #   external resource can only have one of: sample, run, or genome
        constraints = [
            CheckConstraint(
                check = (
                (Q(sample__isnull=False) & Q(run__isnull=False) & Q(genome__isnull=True)) |
                (Q(sample__isnull=False) & Q(run__isnull=True) & Q(genome__isnull=False)) |
                (Q(sample__isnull=False) & Q(run__isnull=False) & Q(genome__isnull=True))
                ),
                name="externalresource_has_only_one_target",
            ),
        ]

    def __str__(self):
        return f"{self.source_system}:{self.accession}"