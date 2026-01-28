from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from versions.models import Version
from samples.models import Sample

from api_fetch.biosamples import get_basic_sample_data
from sample_metadata_curation import curate_biosample

class Command(BaseCommand):
    help = "Fetch BioSample JSON, curate it, and add into the Sample table."

    def add_arguments(self, parser):
        parser.add_argument("--biosample_accession", "-b", type=str, help="BioSample accession, e.g. SAMN... or SAMEA...", required=True)
        parser.add_argument("--source", "-s", type=str, default="", help='Source dataset label, e.g. "MFD"', required=True)
        parser.add_argument("--version-source", "-vs", type=str, default="MFD", help='Version source, e.g. "MFD"')
        parser.add_argument("--version-label", "-vl", type=str, required=True, help='Version label, e.g. "mfd_2026_01_15"')

    @transaction.atomic
    def handle(self, *args, **opts):
        biosample_acc = opts["biosample_accession"]
        source_dataset = opts["source"]
        version_source = opts["version_source"]
        version_label = opts["version_label"]

        version, _ = Version.objects.get_or_create(source=version_source, label=version_label)

        # fetch raw biosample JSON
        try:
            raw = get_basic_sample_data(biosample_acc)
        except Exception as e:
            raise CommandError(f"Failed to fetch BioSample {biosample_acc}: {e}")

        if not raw:
            raise CommandError(f"No BioSample data returned for {biosample_acc}")

        # curate sample fields
        try:
            curated = curate_biosample(raw, biome_keys=[
                "01_mfd_sampletype",
                "02_mfd_areatype",
                "03_mfd_hab1",
                "04_mfd_hab2",
                "05_mfd_hab3"
            ])
            print(curated)
        except Exception as e:
            raise CommandError(f"Failed to curate BioSample {biosample_acc}: {e}")

        lat = curated.get("latitude")
        lon = curated.get("longitude")
        region = curated.get("region")
        locality = curated.get("locality")
        geography_check_status = curated.get("geo_check_status")
        geography_status_reason = curated.get("geo_check_reason")
        biome = curated.get("biome")

        # add to db
        sample, created = Sample.objects.update_or_create(
            biosample_accession=biosample_acc,
            defaults={
                "source_dataset": source_dataset,
                "version": version,
                "latitude": lat,
                "longitude": lon,
                "region": region,
                "locality": locality,
                "geography_check_status": geography_check_status,
                "geography_status_reason": geography_status_reason,
                "ontology": biome,
                "raw_metadata": curated,  # combined dict of curated and raw data
            },
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"{'Created' if created else 'Updated'} Sample {sample.biosample_accession}"
            )
        )
