from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from genomes.models import Genome
from versions.models import IngestVersion, CartogenomicsRelease
from external.models import ExternalResource

from api_fetch.biosamples import get_basic_sample_data
from api_fetch.ena import ENAClient
from sample_metadata_curation.curate import curate_biosample

ena_api = ENAClient()

class Command(BaseCommand):
    help = "Ingest genomes and their quality metrics from BioSamples."

    def add_arguments(self, parser):
        parser.add_argument(
            "--accession",
            "-a",
            type=str,
            required=True,
            help="Genome or Sample Accession, e.g. GCA..., SAME..., ERS...",
        )
        parser.add_argument(
            "--source",
            "-s",
            type=str,
            required=True,
            help='Source system, e.g. "MFD", "GTDB", "MGNIFY"',
        )
        parser.add_argument(
            "--version-label",
            "-vl",
            type=str,
            required=True,
            help='Version label, e.g. "gtdb_r220"',
        )
        parser.add_argument(
            "--pipeline-version",
            "-pv",
            type=str,
            default="",
            help='Pipeline version',
        )
        parser.add_argument(
            "--release-label",
            "-rl",
            type=str,
            default="1.0",
            help='Cartogenomics release label',
        )

    @transaction.atomic
    def handle(self, *args, **opts):
        accession = opts["accession"]
        source_system = opts["source"]
        version_label = opts["version_label"]
        pipeline_version = opts["pipeline_version"]
        release_label = opts["release_label"]

        # 1. Call get_all_genome_accessions
        try:
            accs = ena_api.get_all_genome_accessions(accession)
            genome_acc = accs.get("genome_accession")
            biosample_acc = accs.get("biosample")
            ena_sample_acc = accs.get("ena_sample")
        except Exception as e:
            raise CommandError(f"Failed to get genome accessions for {accession}: {e}")

        if not genome_acc:
            raise CommandError(f"No genome accession found for {accession}")

        fetch_acc = biosample_acc or ena_sample_acc
        if not fetch_acc:
             raise CommandError(f"No sample accession found for {accession}")

        # 2. Call biosamples with the sample as usual
        try:
            raw = get_basic_sample_data(fetch_acc)
        except Exception as e:
            raise CommandError(f"Failed to fetch BioSample {fetch_acc}: {e}")

        if not raw:
            raise CommandError(f"No BioSample data returned for {fetch_acc}")

        # 3. Get completeness_score, contamination_score and completeness_software
        try:
            curated = curate_biosample(raw)
        except Exception as e:
            raise CommandError(f"Failed to curate BioSample {fetch_acc}: {e}")

        completeness = curated.get("completeness_score")
        contamination = curated.get("contamination_score")
        software = curated.get("completeness_software")

        # Set up IngestVersion
        release, _ = CartogenomicsRelease.objects.get_or_create(label=release_label)

        upstream_last_modified = None
        raw_update = raw.get("update")
        if raw_update:
            try:
                upstream_last_modified = timezone.datetime.fromisoformat(raw_update.replace("Z", "+00:00"))
            except ValueError:
                pass

        ingest, _ = IngestVersion.objects.update_or_create(
            source_system=source_system,
            label=version_label,
            data_type=IngestVersion.DataType.GENOMES,
            defaults={
                "pipeline_version": pipeline_version,
                "release": release,
                "retrieved_at": timezone.now(),
                "upstream_last_modified": upstream_last_modified,
            }
        )

        # Update or create Genome
        genome, created = Genome.objects.update_or_create(
            accession=genome_acc,
            ingest=ingest,
            defaults={
                "completeness": completeness,
                "contamination": contamination,
                "completeness_software": software or "",
            },
        )

        # link to genome in ENA
        ExternalResource.objects.update_or_create(
            source_system=ExternalResource.SourceSystem.ENA,
            accession=genome_acc,
            ingest=ingest,
            defaults={
                "url": f"https://www.ebi.ac.uk/ena/browser/view/{genome_acc}",
                "genome": genome,
                "sample": None,
                "run": None,
            },
        )

        # Link to the Sample in BioSamples
        if biosample_acc:
            ExternalResource.objects.update_or_create(
                source_system=ExternalResource.SourceSystem.BIOSAMPLES,
                accession=genome_acc,
                ingest=ingest,
                defaults={
                    "url": f"https://www.ebi.ac.uk/biosamples/samples/{biosample_acc}.json",
                    "genome": genome,
                    "run": None,
                    "sample": None,
                },
            )
        else:
            ExternalResource.objects.update_or_create(
                source_system=ExternalResource.SourceSystem.ENA,
                accession=genome_acc,
                ingest=ingest,
                defaults={
                    "url": f"https://www.ebi.ac.uk/biosamples/samples/{ena_sample_acc}.json",
                    "genome": genome,
                    "run": None,
                    "sample": None,
                },
            )


        self.stdout.write(self.style.SUCCESS(
            f"{'Created' if created else 'Updated'} Genome {genome_acc} linked to BioSample {biosample_acc}"
        ))