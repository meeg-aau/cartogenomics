from django.db import models

class CartogenomicsRelease(models.Model):
    label = models.CharField(max_length=50, unique=True)
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.label

class IngestVersion(models.Model):
    class SourceSystem(models.TextChoices):
        BIOSAMPLES = "BIOSAMPLES", "BioSamples"
        ENA = "ENA", "ENA"
        BIOSTUDIES = "BIOSTUDIES", "BioStudies"
        INTERNAL = "INTERNAL", "Internal"

    class DataType(models.TextChoices):
        SAMPLE_METADATA = "SAMPLE_METADATA", "Sample metadata"
        READS = "READS", "reads"
        GENOMES = "GENOME", "genome"
        ABUNDANCE_RAW = "ABUNDANCE_RAW", "abundance raw"
        ABUNDANCE_PARQUET = "ABUNDANCE_PARQUET", "Abundance parquet"
        RO_CRATE = "RO_CRATE", "RO-crate"

    label = models.CharField(max_length=100)

    source_system = models.CharField(max_length=32, choices=SourceSystem.choices)
    data_type = models.CharField(max_length=32, choices=DataType.choices)
    upstream_version = models.CharField(max_length=100, blank=True, default="")
    last_modified_internal = models.DateTimeField(null=True, blank=True)
    pipeline_version = models.CharField(max_length=100, blank=True, default="")

    release = models.ForeignKey(
        CartogenomicsRelease,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="ingests",
    )

    retrieved_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True, default="")

    class Meta:
        unique_together = ("source_system", "data_type", "label")

    def __str__(self):
        return f"{self.source_system}:{self.label}"
