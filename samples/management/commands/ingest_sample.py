from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from versions.models import IngestVersion
from samples.models import Sample

from api_fetch.biosamples import get_basic_sample_data
from api_fetch.ena import get_sample_accession
from sample_metadata_curation import curate_biosample

class Command(BaseCommand):
    help = "Fetch BioSample JSON, curate it, and add into the Sample table."

    def add_arguments(self, parser):
        parser.add_argument("--accession", "-a", type=str, help="Accession, e.g. SAMN..., ERR..., ERX..., ERS...", required=True)
        parser.add_argument("--source", "-s", type=str, default="", help='Source dataset label, e.g. "MFD"', required=True)
        parser.add_argument("--version-source", "-vs", type=str, default="MFD", help='Version source, e.g. "MFD"')
        parser.add_argument("--version-label", "-vl", type=str, required=True, help='Version label, e.g. "mfd_2026_01_15"')

    @transaction.atomic
    def handle(self, *args, **opts):
        accession = opts["accession"]
        source_dataset = opts["source"]
        version_source = opts["version_source"]
        version_label = opts["version_label"]

        version, _ = IngestVersion.objects.get_or_create(source=version_source, label=version_label)

        # get accessions from ENA
        try:
            accs = get_sample_accession(accession)
            biosample_acc = accs.get("biosample")
            ena_sample_acc = accs.get("ena_sample")
        except Exception as e:
            raise CommandError(f"Failed to get accessions for {accession}: {e}")

        # fetch raw biosample JSON using biosample_acc if it exists, otherwise ena_sample_acc
        fetch_acc = biosample_acc or ena_sample_acc
        if not fetch_acc:
            raise CommandError(f"Could not find a valid sample accession for {accession}")

        try:
            raw = get_basic_sample_data(fetch_acc)
        except Exception as e:
            raise CommandError(f"Failed to fetch BioSample {fetch_acc}: {e}")

        if not raw:
            raise CommandError(f"No BioSample data returned for {fetch_acc}")

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
            raise CommandError(f"Failed to curate BioSample {fetch_acc}: {e}")

        lat = curated.get("latitude")
        lon = curated.get("longitude")
        region = curated.get("region")
        locality = curated.get("locality")
        geography_check_status = curated.get("geo_check_status")
        geography_status_reason = curated.get("geo_check_reason")
        biome = curated.get("biome")

        # add to db
        # Use ena_sample or biosample to identify the record.
        # Since we want to update if either matches (though usually they come together),
        # but update_or_create needs a unique set of lookup fields.
        # Given both are unique now, we can try to look up by ena_sample if it exists,
        # or biosample.
        
        lookup = {}
        if ena_sample_acc:
            lookup["ena_sample"] = ena_sample_acc
        elif biosample_acc:
            lookup["biosample"] = biosample_acc
        else:
            raise CommandError("Neither ena_sample nor biosample accession found")

        sample, created = Sample.objects.update_or_create(
            **lookup,
            defaults={
                "ena_sample": ena_sample_acc,
                "biosample": biosample_acc,
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
                f"{'Created' if created else 'Updated'} Sample {sample}"
            )
        )
