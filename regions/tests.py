import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import requests
from django.contrib.gis.geos import MultiPolygon, Point, Polygon
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from regions.management.commands.ingest_country_boundaries import (
    INGEST_VERSION_LABEL,
    NATURAL_EARTH_URL,
)
from regions.models import CountryBoundary
from versions.models import IngestVersion

DENMARK_POLYGON = Polygon(
    ((8.0, 54.5), (8.0, 57.7), (12.7, 57.7), (12.7, 54.5), (8.0, 54.5))
)


class CountryBoundaryModelTest(TestCase):
    def test_str(self):
        boundary = CountryBoundary.objects.create(
            iso_two_cc="DK", name="Denmark", geom=MultiPolygon(DENMARK_POLYGON)
        )
        self.assertEqual(str(boundary), "Denmark (DK)")

    def test_point_within_boundary(self):
        boundary = CountryBoundary.objects.create(
            iso_two_cc="DK", name="Denmark", geom=MultiPolygon(DENMARK_POLYGON)
        )
        copenhagen = Point(12.57, 55.68, srid=4326)
        self.assertTrue(
            CountryBoundary.objects.filter(
                geom__contains=copenhagen, pk=boundary.pk
            ).exists()
        )


def _fake_ne_zip(directory: Path, version: str = "5.1.1") -> Path:
    zip_path = directory / "ne_10m_admin_0_countries.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("ne_10m_admin_0_countries.shp", b"")
        zf.writestr("ne_10m_admin_0_countries.VERSION.txt", version)
    return zip_path


class IngestCountryBoundariesCommandTest(TestCase):
    """
    Tests command orchestration (download vs --source, --clear, --clear,
    IngestVersion provenance, error handling). LayerMapping/GDAL shapefile
    parsing itself is mocked - that's Django's own tested code, not ours to
    re-verify here.
    """

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)

    def _persisted_zip_path(self) -> str:
        #   NATURAL_EARTH_ZIP_PATH's parent gets mkdir'd and written to on
        #   every download, so tests must point it into their own tmp dir
        #   rather than the real project data/ directory
        return str(Path(self.tmp_dir.name) / "persisted" / "ne_countries.zip")

    @patch("regions.management.commands.ingest_country_boundaries.requests.get")
    @patch("regions.management.commands.ingest_country_boundaries.LayerMapping")
    def test_downloads_when_no_source_given(self, mock_lm, mock_get):
        zip_path = _fake_ne_zip(Path(self.tmp_dir.name))
        mock_get.return_value.content = zip_path.read_bytes()
        mock_get.return_value.raise_for_status = lambda: None

        with self.settings(NATURAL_EARTH_ZIP_PATH=self._persisted_zip_path()):
            call_command("ingest_country_boundaries")

        mock_get.assert_called_once_with(NATURAL_EARTH_URL, timeout=120)
        mock_lm.assert_called_once()
        mock_lm.return_value.save.assert_called_once()

    @patch("regions.management.commands.ingest_country_boundaries.requests.get")
    @patch("regions.management.commands.ingest_country_boundaries.LayerMapping")
    def test_downloads_straight_to_persisted_path(self, mock_lm, mock_get):
        zip_path = _fake_ne_zip(Path(self.tmp_dir.name))
        mock_get.return_value.content = zip_path.read_bytes()
        mock_get.return_value.raise_for_status = lambda: None
        persisted_path = self._persisted_zip_path()

        with self.settings(NATURAL_EARTH_ZIP_PATH=persisted_path):
            call_command("ingest_country_boundaries")

        self.assertEqual(Path(persisted_path).read_bytes(), zip_path.read_bytes())

    @patch("regions.management.commands.ingest_country_boundaries.requests.get")
    @patch("regions.management.commands.ingest_country_boundaries.LayerMapping")
    def test_upstream_version_captured_from_version_txt(self, mock_lm, mock_get):
        zip_path = _fake_ne_zip(Path(self.tmp_dir.name), version="5.1.1")
        mock_get.return_value.content = zip_path.read_bytes()
        mock_get.return_value.raise_for_status = lambda: None

        with self.settings(NATURAL_EARTH_ZIP_PATH=self._persisted_zip_path()):
            call_command("ingest_country_boundaries")

        version = IngestVersion.objects.get(
            source_system=IngestVersion.SourceSystem.NATURAL_EARTH,
            data_type=IngestVersion.DataType.COUNTRY_BOUNDARIES,
            label=INGEST_VERSION_LABEL,
        )
        self.assertEqual(version.upstream_version, "5.1.1")

    @patch("regions.management.commands.ingest_country_boundaries.requests.get")
    @patch("regions.management.commands.ingest_country_boundaries.LayerMapping")
    def test_source_flag_skips_download_but_still_reads_version(
        self, mock_lm, mock_get
    ):
        zip_path = _fake_ne_zip(Path(self.tmp_dir.name), version="5.1.1")

        call_command("ingest_country_boundaries", source=str(zip_path))

        mock_get.assert_not_called()
        mock_lm.assert_called_once()
        version = IngestVersion.objects.get(
            source_system=IngestVersion.SourceSystem.NATURAL_EARTH,
            data_type=IngestVersion.DataType.COUNTRY_BOUNDARIES,
            label=INGEST_VERSION_LABEL,
        )
        self.assertEqual(version.upstream_version, "5.1.1")

    def test_missing_version_txt_raises_command_error(self):
        zip_path = Path(self.tmp_dir.name) / "no_version.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("ne_10m_admin_0_countries.shp", b"")

        with self.assertRaises(CommandError) as cm:
            call_command("ingest_country_boundaries", source=str(zip_path))
        self.assertIn("VERSION.txt", str(cm.exception))

    @patch("regions.management.commands.ingest_country_boundaries.LayerMapping")
    def test_new_rows_get_ingest_attached(self, mock_lm):
        zip_path = _fake_ne_zip(Path(self.tmp_dir.name))

        def _fake_save(*args, **kwargs):
            CountryBoundary.objects.create(
                iso_two_cc="DK", name="Denmark", geom=MultiPolygon(DENMARK_POLYGON)
            )

        mock_lm.return_value.save.side_effect = _fake_save

        call_command("ingest_country_boundaries", source=str(zip_path))

        boundary = CountryBoundary.objects.get(iso_two_cc="DK")
        self.assertIsNotNone(boundary.ingest)
        self.assertEqual(boundary.ingest.label, INGEST_VERSION_LABEL)

    def test_missing_source_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("ingest_country_boundaries", source="/no/such/file.zip")

    @patch("regions.management.commands.ingest_country_boundaries.requests.get")
    def test_download_failure_raises_command_error(self, mock_get):
        mock_get.side_effect = Exception("network down")
        with self.settings(NATURAL_EARTH_ZIP_PATH=self._persisted_zip_path()):
            with self.assertRaises(CommandError) as cm:
                call_command("ingest_country_boundaries")
        self.assertIn("Failed to download", str(cm.exception))

    @patch("regions.management.commands.ingest_country_boundaries.LayerMapping")
    def test_clear_deletes_existing_rows_first(self, mock_lm):
        zip_path = _fake_ne_zip(Path(self.tmp_dir.name))
        CountryBoundary.objects.create(
            iso_two_cc="XX", name="Placeholder", geom=MultiPolygon(DENMARK_POLYGON)
        )

        call_command("ingest_country_boundaries", source=str(zip_path), clear=True)

        self.assertEqual(CountryBoundary.objects.count(), 0)
        mock_lm.assert_called_once()

    def test_no_shp_in_zip_raises_command_error(self):
        zip_path = Path(self.tmp_dir.name) / "empty.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("readme.txt", "no shapefile here")

        with self.assertRaises(CommandError) as cm:
            call_command("ingest_country_boundaries", source=str(zip_path))
        self.assertIn("No .shp file found", str(cm.exception))


class NaturalEarthUrlReachabilityTest(unittest.TestCase):
    """
    Real network check (no mocking, no DB) that the Natural Earth URL we share
    with sample-metadata-curation's install_resources.py is still live.
    """

    def test_natural_earth_url_is_reachable(self):
        try:
            response = requests.head(
                NATURAL_EARTH_URL, timeout=30, allow_redirects=True
            )
        except requests.RequestException as e:
            self.fail(f"Natural Earth URL unreachable: {e}")
        self.assertEqual(
            response.status_code,
            200,
            f"Expected 200 from {NATURAL_EARTH_URL}, got {response.status_code}",
        )
