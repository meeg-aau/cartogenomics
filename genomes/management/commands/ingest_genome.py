import logging

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from genomes.models import Genome
from versions.models import IngestVersion, CartogenomicsRelease
from external.models import ExternalResource

from api_fetch.biosamples import get_basic_sample_data
from api_fetch.ena import ENAClient
from sample_metadata_curation.curate import curate_biosample

logger = logging.getLogger(__name__)
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
            # ENA date fields returned alongside accessions
            ena_first_created_raw = accs.get("first_created")
            ena_last_updated_raw = accs.get("last_updated")
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

        # BioSamples date fields:
        #   "update"    → when BioSamples last modified the record
        #   "submitted" → when the record was first submitted to BioSamples
        upstream_last_modified = None
        raw_update = raw.get("update")
        if raw_update:
            try:
                dt = timezone.datetime.fromisoformat(raw_update.replace("Z", "+00:00"))
                upstream_last_modified = dt if timezone.is_aware(dt) else timezone.make_aware(dt)
            except (ValueError, TypeError):
                pass

        biosample_first_created = None
        raw_submitted = raw.get("submitted")
        if raw_submitted:
            try:
                dt = timezone.datetime.fromisoformat(raw_submitted.replace("Z", "+00:00"))
                biosample_first_created = dt if timezone.is_aware(dt) else timezone.make_aware(dt)
            except (ValueError, TypeError):
                pass

        # ENA date fields from get_all_genome_accessions:
        #   "first_created" → when the assembly record first appeared in ENA
        #   "last_updated"  → when ENA last updated the assembly record
        ena_first_created = None
        if ena_first_created_raw:
            try:
                dt = timezone.datetime.fromisoformat(ena_first_created_raw.replace("Z", "+00:00"))
                ena_first_created = dt if timezone.is_aware(dt) else timezone.make_aware(dt)
            except (ValueError, TypeError):
                pass

        ena_last_updated = None
        if ena_last_updated_raw:
            try:
                dt = timezone.datetime.fromisoformat(ena_last_updated_raw.replace("Z", "+00:00"))
                ena_last_updated = dt if timezone.is_aware(dt) else timezone.make_aware(dt)
            except (ValueError, TypeError):
                pass

        ingest, _ = IngestVersion.objects.update_or_create(
            source_system=IngestVersion.SourceSystem.ENA,
            label=version_label,
            data_type=IngestVersion.DataType.GENOMES,
            defaults={
                "pipeline_version": pipeline_version,
                "release": release,
                "last_modified_internal": upstream_last_modified,
            }
        )

        # Detect changes on re-ingest and record previous ingest
        curated_defaults = {
            "completeness": completeness,
            "contamination": contamination,
            "completeness_software": software or "",
        }

        previous_ingest = None
        try:
            existing = Genome.objects.get(accession=genome_acc)
            changed_fields = [
                field for field, value in curated_defaults.items()
                if getattr(existing, field) != value
            ]
            if changed_fields:
                logger.info(
                    f"Genome {genome_acc} already exists (id={existing.pk}) — "
                    f"{len(changed_fields)} field(s) changed: {changed_fields}. "
                    f"Updating and recording previous IngestVersion id={existing.ingest_id}."
                )
                previous_ingest = existing.ingest
            else:
                logger.info(
                    f"Genome {genome_acc} already exists (id={existing.pk}) — no fields changed. "
                    "Updating ingest pointer only."
                )
        except Genome.DoesNotExist:
            logger.info(f"Genome {genome_acc} not found in DB — will be created.")

        defaults = {**curated_defaults, "ingest": ingest}
        if previous_ingest is not None:
            defaults["previous_ingest"] = previous_ingest

        genome, created = Genome.objects.update_or_create(
            accession=genome_acc,
            defaults=defaults,
        )

        # Link to genome assembly page in ENA (dates from ENA API)
        ExternalResource.objects.update_or_create(
            source_system=ExternalResource.SourceSystem.ENA,
            accession=genome_acc,
            ingest=ingest,
            defaults={
                "url": f"https://www.ebi.ac.uk/ena/browser/view/{genome_acc}",
                "genome": genome,
                "sample": None,
                "run": None,
                "first_created_external": ena_first_created,
                "last_modified_external": ena_last_updated,
            },
        )

        # Link to the BioSamples record for this genome (dates from BioSamples API)
        sample_acc_for_url = biosample_acc or ena_sample_acc
        if sample_acc_for_url:
            ExternalResource.objects.update_or_create(
                source_system=ExternalResource.SourceSystem.BIOSAMPLES if biosample_acc else ExternalResource.SourceSystem.ENA,
                accession=genome_acc,
                ingest=ingest,
                defaults={
                    "url": f"https://www.ebi.ac.uk/biosamples/samples/{sample_acc_for_url}.json",
                    "genome": genome,
                    "run": None,
                    "sample": None,
                    "first_created_external": biosample_first_created,
                    "last_modified_external": upstream_last_modified,
                },
            )


        self.stdout.write(self.style.SUCCESS(
            f"{'Created' if created else 'Updated'} Genome {genome_acc} linked to BioSample {biosample_acc}"
        ))