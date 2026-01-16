from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from versions.models import Version
from samples.models import Sample

from api_fetch.biosamples import get_basic_sample_data
from sample_metadata_curation import curate

class Command(BaseCommand):
    help = "Fetch BioSample JSON, curate it, and upsert into the Sample table."

    def add_arguments(self, parser):
        parser.add_argument("biosample_accession", type=str, help="BioSample accession, e.g. SAMN... or SAMEA...")
        parser.add_argument("--source", type=str, default="", help='Source dataset label, e.g. "MFD"')
        parser.add_argument("--version-source", type=str, default="MFD", help='Version source, e.g. "MFD"')
        parser.add_argument("--version-label", type=str, required=True, help='Version label, e.g. "mfd_2026_01_15"')

    @transaction.atomic
    def handle(self, *args, **opts):
        biosample_acc = opts["biosample_accession"]
        source_dataset = opts["source"]
        version_source = opts["version_source"]
        version_label = opts["version_label"]

        # 1) Ensure Version exists
        version, _ = Version.objects.get_or_create(source=version_source, label=version_label)

        # 2) Fetch raw biosamples JSON
        try:
            raw = fetch_biosample_json(biosample_acc)
        except Exception as e:
            raise CommandError(f"Failed to fetch BioSample {biosample_acc}: {e}")

        if not raw:
            raise CommandError(f"No BioSample data returned for {biosample_acc}")

        # 3) Curate/clean -> dict
        try:
            curated = curate_sample(raw)
        except Exception as e:
            raise CommandError(f"Failed to curate BioSample {biosample_acc}: {e}")

        # 4) Pull out common fields if your curated dict includes them
        #    Adjust these keys to match what curate_sample returns.
        lat = curated.get("latitude")
        lon = curated.get("longitude")
        location = curated.get("location") or curated.get("country") or curated.get("geo_loc_name")

        # 5) Upsert into DB
        sample, created = Sample.objects.update_or_create(
            biosample_accession=biosample_acc,
            defaults={
                "source_dataset": source_dataset,
                "version": version,
                "latitude": lat,
                "longitude": lon,
                "location": location,
                "raw_metadata": curated,  # store curated dict here (you can also store raw separately later)
            },
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"{'Created' if created else 'Updated'} Sample {sample.biosample_accession}"
            )
        )
