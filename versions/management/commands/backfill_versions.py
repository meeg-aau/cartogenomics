import logging

from django.core.management.base import BaseCommand
from django.db import transaction

from genomes.models import Genome, GenomeVersion
from samples.models import Sample, SampleVersion

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Backfill SampleVersion and GenomeVersion rows for existing "
        "records that have none."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--samples-only",
            action="store_true",
            help="Only backfill SampleVersion rows",
        )
        parser.add_argument(
            "--genomes-only",
            action="store_true",
            help="Only backfill GenomeVersion rows",
        )

    @transaction.atomic
    def handle(self, *args, **opts):
        samples_only = opts["samples_only"]
        genomes_only = opts["genomes_only"]

        if not genomes_only:
            self._backfill_samples()

        if not samples_only:
            self._backfill_genomes()

    def _backfill_samples(self):
        already_versioned = set(
            SampleVersion.objects.filter(valid_to__isnull=True).values_list(
                "sample_id", flat=True
            )
        )

        to_create = []
        skipped = 0
        for sample in Sample.objects.select_related("ingest").all():
            if sample.pk in already_versioned:
                skipped += 1
                continue
            if sample.ingest_id is None:
                logger.warning(
                    f"Sample id={sample.pk} ({sample}) has no ingest — skipping."
                )
                skipped += 1
                continue
            to_create.append(
                SampleVersion(
                    sample=sample,
                    ingest=sample.ingest,
                    valid_from=sample.ingest.ingested_on,
                    valid_to=None,
                    biosample=sample.biosample,
                    ena_sample=sample.ena_sample,
                    source_dataset=sample.source_dataset,
                    latitude=sample.latitude,
                    longitude=sample.longitude,
                    region=sample.region,
                    locality=sample.locality,
                    ontology=sample.ontology,
                    geography_check_status=sample.geography_check_status,
                    geography_status_reason=sample.geography_status_reason,
                    raw_metadata=sample.raw_metadata,
                )
            )

        SampleVersion.objects.bulk_create(to_create)
        self.stdout.write(
            self.style.SUCCESS(
                f"SampleVersion: created {len(to_create)}, skipped {skipped}"
            )
        )

    def _backfill_genomes(self):
        already_versioned = set(
            GenomeVersion.objects.filter(valid_to__isnull=True).values_list(
                "genome_id", flat=True
            )
        )

        to_create = []
        skipped = 0
        for genome in Genome.objects.select_related("ingest").all():
            if genome.pk in already_versioned:
                skipped += 1
                continue
            to_create.append(
                GenomeVersion(
                    genome=genome,
                    ingest=genome.ingest,
                    valid_from=genome.ingest.ingested_on,
                    valid_to=None,
                    completeness=genome.completeness,
                    contamination=genome.contamination,
                    completeness_software=genome.completeness_software,
                    genome_size=genome.genome_size,
                    n50=genome.n50,
                    taxonomy=genome.taxonomy,
                )
            )

        GenomeVersion.objects.bulk_create(to_create)
        self.stdout.write(
            self.style.SUCCESS(
                f"GenomeVersion: created {len(to_create)}, skipped {skipped}"
            )
        )
