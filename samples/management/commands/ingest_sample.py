from django.utils import timezone
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from versions.models import IngestVersion, CartogenomicsRelease
from samples.models import Sample

from api_fetch.biosamples import get_basic_sample_data
from api_fetch.ena import ENAClient
from sample_metadata_curation.curate import curate_biosample

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
            "--sample-type",
            "-t",
            type=str,
            default="run",
            choices=["run", "genome"],
            help="Type of sample: run or genome",
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
        sample_type = opts["sample_type"]
        pipeline_version = opts["pipeline_version"]
        release_label = opts["release_label"]

        # Get related accessions from ENA
        try:
            accs = ena_api.get_all_accessions(accession)
            biosample_acc = accs.get("biosample")
            ena_sample_acc = accs.get("ena_sample")
        except Exception as e:
            raise CommandError(f"Failed to get accessions for {accession}: {e}")

        # Fetch raw BioSample JSON using biosample_acc if available,
        # otherwise fall back to ena_sample_acc
        fetch_acc = biosample_acc or ena_sample_acc
        if not fetch_acc:
            raise CommandError(
                f"Could not find a valid sample accession for {accession}"
            )

        try:
            raw = get_basic_sample_data(fetch_acc)
        except Exception as e:
            raise CommandError(f"Failed to fetch BioSample {fetch_acc}: {e}")

        if not raw:
            raise CommandError(f"No BioSample data returned for {fetch_acc}")

        # Set up IngestVersion
        release, _ = CartogenomicsRelease.objects.get_or_create(label=release_label)
        
        # Upstream last modified from BioSample JSON 'update' field
        # Format: "2025-01-22T13:55:00.113Z"
        upstream_last_modified = None
        raw_update = raw.get("update")
        if raw_update:
            try:
                upstream_last_modified = timezone.datetime.fromisoformat(raw_update.replace("Z", "+00:00"))
            except ValueError:
                pass

        version, _ = IngestVersion.objects.update_or_create(
            source_system=IngestVersion.SourceSystem.BIOSAMPLES,
            label=version_label,
            data_type=IngestVersion.DataType.SAMPLE_METADATA,
            defaults={
                "pipeline_version": pipeline_version,
                "release": release,
                "retrieved_at": timezone.now(),
                "upstream_last_modified": upstream_last_modified,
                "upstream_version": "",
            }
        )

        # Curate sample fields
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

        defaults = {
            "biosample": biosample_acc,
            "ena_sample": ena_sample_acc,
            "source_dataset": source_dataset,
            "ingest": version,
            "latitude": curated.get("latitude"),
            "longitude": curated.get("longitude"),
            "region": curated.get("region"),
            "locality": curated.get("locality"),
            "geography_check_status": curated.get("geo_check_status"),
            "geography_status_reason": curated.get("geo_check_reason"),
            "ontology": curated.get("biome"),
            "raw_metadata": curated,
        }

        if sample_type == "genome":
            defaults.update(
                {
                    "completeness_score": curated.get("completeness_score"),
                    "contamination_score": curated.get("contamination_score"),
                    "completeness_software": curated.get("completeness_software"),
                }
            )

        try:
            sample, created = Sample.objects.update_or_create(
                **lookup,
                defaults=defaults,
            )
        except Exception as e:
            raise CommandError(f"Failed to create/update Sample for {accession}: {e}")

        self.stdout.write(
            self.style.SUCCESS(
                f"{'Created' if created else 'Updated'} Sample {sample}"
            )
        )