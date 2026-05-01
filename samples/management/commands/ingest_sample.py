import logging

from datetime import datetime
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from versions.models import IngestVersion, CartogenomicsRelease
from samples.models import Sample
from external.models import ExternalResource

from api_fetch.biosamples import get_basic_sample_data, BASE_URL
from api_fetch.ena import ENAClient
from sample_metadata_curation.curate import curate_biosample

logger = logging.getLogger(__name__)
ena_api = ENAClient()


class Command(BaseCommand):
    help = "Fetch BioSample JSON, curate it, and add it into the Sample table."

    def add_arguments(self, parser):
        parser.add_argument(
            "--accession",
            "-a",
            type=str,
            required=True,
            help="Accession, e.g. SAME..., ERR..., ERX..., ERS...",
        )
        parser.add_argument(
            "--source",
            "-s",
            type=str,
            required=True,
            help='Source dataset label, e.g. "MFD"',
        )
        parser.add_argument(
            "--version-label",
            "-vl",
            type=str,
            required=True,
            help='Version label, e.g. "mfd_2026_01_15"',
        )
        parser.add_argument(
            "--pipeline-version",
            "-pv",
            type=str,
            default="sample_metadata_curation 0.1.0",
            help='Pipeline version, e.g. "sample_metadata_curation 0.1.0"',
        )
        parser.add_argument(
            "--release-label",
            "-rl",
            type=str,
            default="1.0",
            help='Cartogenomics release label, default is "1.0"',
        )

    @transaction.atomic
    def handle(self, *args, **opts):
        accession = opts["accession"]
        source_dataset = opts["source"]
        version_label = opts["version_label"]
        pipeline_version = opts["pipeline_version"]
        release_label = opts["release_label"]

        logger.info(f"Starting ingest for accession: {accession}")

        # Get related accessions from ENA
        try:
            accs = ena_api.get_all_run_accessions(accession)
            biosample_acc = accs.get("biosample")
            ena_sample_acc = accs.get("ena_sample")
        except Exception as e:
            raise CommandError(f"Failed to get accessions for {accession}: {e}")

        logger.debug(f"Resolved accessions: biosample={biosample_acc} ena_sample={ena_sample_acc}")

        # Fetch raw BioSample JSON using biosample_acc if available, otherwise fall back to ena_sample_acc
        fetch_acc = biosample_acc or ena_sample_acc
        if not fetch_acc:
            raise CommandError(
                f"Could not find a valid sample accession for {accession}"
            )

        logger.info(f"Fetching BioSample metadata for {fetch_acc}")
        try:
            raw = get_basic_sample_data(fetch_acc)
        except Exception as e:
            raise CommandError(f"Failed to fetch BioSample {fetch_acc}: {e}")

        if not raw:
            raise CommandError(f"No BioSample data returned for {fetch_acc}")

        # Set up IngestVersion
        release, _ = CartogenomicsRelease.objects.get_or_create(label=release_label)

        # BioSamples date fields:
        #   "update" → when the record was last modified
        #   "submitted" → when the record was first submitted to BioSamples
        upstream_last_modified = None
        raw_update = raw.get("update")
        if raw_update:
            try:
                upstream_last_modified = datetime.fromisoformat(raw_update.replace("Z", "+00:00"))
            except ValueError:
                logger.warning(f"Could not parse BioSamples 'update' date: {raw_update}")

        biosample_first_created = None
        raw_submitted = raw.get("submitted")
        if raw_submitted:
            try:
                biosample_first_created = datetime.fromisoformat(raw_submitted.replace("Z", "+00:00"))
            except ValueError:
                logger.warning(f"Could not parse BioSamples 'submitted' date: {raw_submitted}")

        version, version_created = IngestVersion.objects.update_or_create(
            source_system=IngestVersion.SourceSystem.BIOSAMPLES,
            label=version_label,
            data_type=IngestVersion.DataType.SAMPLE_METADATA,
            defaults={
                "pipeline_version": pipeline_version,
                "release": release,
                "last_modified_internal": upstream_last_modified,
                "upstream_version": None,
            }
        )
        logger.debug(f"IngestVersion id={version.pk} label={version.label}", "Created" if version_created else "Using existing")

        # Curate sample fields
        logger.info(f"Curating metadata for {fetch_acc}")
        try:
            curated = curate_biosample(
                raw,
                biome_keys=[
                    "01_mfd_sampletype",
                    "02_mfd_areatype",
                    "03_mfd_hab1",
                    "04_mfd_hab2",
                    "05_mfd_hab3",
                ],
            )
        except Exception as e:
            raise CommandError(f"Failed to curate BioSample {fetch_acc}: {e}")

        # Choose a stable lookup key for update_or_create
        lookup = {}
        if biosample_acc:
            lookup["biosample"] = biosample_acc
        elif ena_sample_acc:
            lookup["ena_sample"] = ena_sample_acc
        else:
            raise CommandError(
                f"Could not determine a lookup key for Sample from {accession}"
            )

        curated_defaults = {
            "biosample": biosample_acc,
            "ena_sample": ena_sample_acc,
            "source_dataset": source_dataset,
            "latitude": curated.get("latitude"),
            "longitude": curated.get("longitude"),
            "region": curated.get("region"),
            "locality": curated.get("locality"),
            "geography_check_status": curated.get("geo_check_status"),
            "geography_status_reason": curated.get("geo_check_reason"),
            "ontology": curated.get("biome"),
            "raw_metadata": curated,
        }

        # Detect whether any curated field changed on re-ingest
        previous_ingest = None
        try:
            existing = Sample.objects.get(**lookup)
            changed_fields = [
                field for field, value in curated_defaults.items()
                if getattr(existing, field) != value
            ]
            if changed_fields:
                logger.info(
                    f"Sample {fetch_acc} already exists (id={existing.pk}) — {len(changed_fields)} field(s) changed: {changed_fields}. "
                    f"Updating in place and recording previous IngestVersion id={existing.ingest}."
                )
                previous_ingest = existing.ingest
            else:
                logger.info(
                    f"Sample {fetch_acc} already exists (id={existing.pk}) and no curated fields have changed. "
                    "Updating ingest pointer only — existing row preserved as is."
                )
        except Sample.DoesNotExist:
            logger.info(f"Sample {fetch_acc} not found in DB — will be created.")

        defaults = {**curated_defaults, "ingest": version}
        if previous_ingest is not None:
            defaults["previous_ingest"] = previous_ingest

        try:
            sample, created = Sample.objects.update_or_create(
                **lookup,
                defaults=defaults,
            )
        except Exception as e:
            raise CommandError(f"Failed to create/update Sample for {accession}: {e}")

        logger.info(f"Sample id={sample.pk} ({sample})", "Created" if created else "Updated")

        # Populate ExternalResource for BioSamples
        logger.debug(f"ExternalResource for {sample.biosample}")
        try:
            ExternalResource.objects.update_or_create(
                source_system=ExternalResource.SourceSystem.BIOSAMPLES,
                accession=sample.biosample,
                ingest=version,
                defaults={
                    "url": f"{BASE_URL}/{sample.biosample}",
                    "sample": sample,
                    "run": None,
                    "genome": None,
                    "first_created_external": biosample_first_created,
                    "last_modified_external": upstream_last_modified,
                },
            )
        except Exception as e:
            raise CommandError(f"Failed to create/update ExternalResource for {accession}: {e}")

        logger.info(f"Ingest complete for {fetch_acc}")
        self.stdout.write(
            self.style.SUCCESS(
                f"{'Created' if created else 'Updated'} Sample {sample}"
            )
        )