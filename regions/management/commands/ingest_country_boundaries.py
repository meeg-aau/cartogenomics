import logging
import shutil
import tempfile
import zipfile
from pathlib import Path

import requests
from django.conf import settings
from django.contrib.gis.utils import LayerMapping
from django.core.management.base import BaseCommand, CommandError

from regions.models import CountryBoundary
from versions.models import IngestVersion

logger = logging.getLogger(__name__)


NATURAL_EARTH_URL = (
    "https://naturalearth.s3.amazonaws.com/10m_cultural/ne_10m_admin_0_countries.zip"
)

INGEST_VERSION_LABEL = "ne_10m_admin_0_countries"

COUNTRY_BOUNDARY_MAPPING = {
    "iso_two_cc": "ISO_A2_EH",
    "name": "NAME",
    "geom": "MULTIPOLYGON",
}


class Command(BaseCommand):
    help = "Load Natural Earth country boundary polygons into CountryBoundary."

    def add_arguments(self, parser):
        parser.add_argument(
            "--source",
            type=str,
            help="Path to a local ne_10m_admin_0_countries.zip (skips downloading).",
        )
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Delete existing CountryBoundary rows before loading.",
        )

    def handle(self, *args, **options):
        source = options.get("source")
        tmp_dir = Path(tempfile.mkdtemp(prefix="ne_countries_"))
        try:
            if source:
                #   a manual override for a one-off run - doesn't update the
                #   persisted "current" copy ingest_sample reads from
                zip_path = Path(source)
                if not zip_path.exists():
                    raise CommandError(f"{zip_path} does not exist")
            else:
                #   download straight to the persisted path - it's the file
                #   ingest_sample hands to sample_metadata_curation, no
                #   separate copy step needed
                zip_path = Path(settings.NATURAL_EARTH_ZIP_PATH)
                zip_path.parent.mkdir(parents=True, exist_ok=True)
                logger.info("Downloading Natural Earth country boundaries...")
                try:
                    response = requests.get(NATURAL_EARTH_URL, timeout=120)
                    response.raise_for_status()
                except Exception as e:
                    raise CommandError(f"Failed to download Natural Earth data: {e}")
                zip_path.write_bytes(response.content)

            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(tmp_dir)

            shp_files = list(tmp_dir.glob("*.shp"))
            if not shp_files:
                raise CommandError(f"No .shp file found in {zip_path}")
            shp_path = shp_files[0]

            #   Natural Earth bundles the actual release version (e.g.
            #   "5.1.1") in a *.VERSION.txt file inside the zip - unlike HTTP
            #   headers (Last-Modified/ETag), this is authoritative and
            #   present the same way whether downloaded fresh or loaded from
            #   a local --source file
            version_files = list(tmp_dir.glob("*.VERSION.txt"))
            if not version_files:
                raise CommandError(
                    f"No *.VERSION.txt file found in {zip_path} - "
                    "can't determine Natural Earth version"
                )
            upstream_version = version_files[0].read_text().strip()

            if options["clear"]:
                deleted, _ = CountryBoundary.objects.all().delete()
                logger.info(f"Cleared {deleted} existing CountryBoundary row(s)")

            version, _ = IngestVersion.objects.update_or_create(
                source_system=IngestVersion.SourceSystem.NATURAL_EARTH,
                data_type=IngestVersion.DataType.COUNTRY_BOUNDARIES,
                label=INGEST_VERSION_LABEL,
                defaults={"upstream_version": upstream_version},
            )

            lm = LayerMapping(
                CountryBoundary,
                shp_path,
                COUNTRY_BOUNDARY_MAPPING,
            )
            lm.save(strict=True, verbose=options["verbosity"] > 1)
            #   LayerMapping's mapping dict only covers fields present in the
            #   shapefile, so attach ingest provenance to the newly created rows
            #   in a single follow-up update
            CountryBoundary.objects.filter(ingest__isnull=True).update(ingest=version)

            count = CountryBoundary.objects.count()
            self.stdout.write(
                self.style.SUCCESS(
                    f"Loaded {count} country boundaries "
                    f"(natural_earth_version={upstream_version})"
                )
            )
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
