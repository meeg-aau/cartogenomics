from django.test import TestCase
from django.core.management import call_command
from unittest.mock import patch, MagicMock
from samples.models import Sample
from versions.models import IngestVersion
from external.models import ExternalResource
from django.core.management.base import CommandError
import io

class IngestSampleTest(TestCase):

    def setUp(self):
        # The IngestVersion model has unique_together = ("source_system", "data_type", "label")
        # However, the command currently uses:
        # version, _ = IngestVersion.objects.get_or_create(source=version_source, label=version_label)
        # We need to see if the command even runs with the current models.
        pass

    @patch("samples.management.commands.ingest_sample.ena_api")
    @patch("samples.management.commands.ingest_sample.get_basic_sample_data")
    @patch("samples.management.commands.ingest_sample.curate_biosample")
    def test_ingest_sample_genome_success(self, mock_curate, mock_get_data, mock_ena_api):
        """Test ingesting a genome sample using real data snippets from SAMN40012083."""
        # Setup mocks
        mock_ena_api.get_all_accessions.return_value = {
            "ena_run": None,
            "ena_experiment": None,
            "biosample": "SAMN40012083",
            "ena_sample": "ERS22960362"
        }
        
        # Real BioSample data for SAMN40012083
        mock_get_data.return_value = {
            "name": "MFD13461_ilm_asm_bin19",
            "accession": "SAMN40012083",
            "sraAccession": "ERS22960362",
            "update": "2025-01-22T13:55:00.113Z",
        }
        
        # Real curated data for SAMN40012083
        mock_curate.return_value = {
            "accession": "SAMN40012083",
            "latitude": 56.06193416,
            "longitude": 8.63495532,
            "geo_check_status": "PASS",
            "geo_check_reason": "match",
            "region": "Denmark",
            "locality": None,
            "biome": "metagenomic assembly",
            "completeness_score": "96.54",
            "contamination_score": "0.08",
            "completeness_software": "CheckM2"
        }

        out = io.StringIO()
        call_command(
            "ingest_sample",
            accession="SAMN40012083",
            source="MFD",
            sample_type="genome",
            version_label="test_v1",
            pipeline_version="custom_pipeline 2.0.0",
            release_label="2.0",
            stdout=out
        )

        # Verify Sample was created
        sample = Sample.objects.get(biosample="SAMN40012083")
        self.assertEqual(sample.latitude, 56.06193416)
        self.assertEqual(sample.longitude, 8.63495532)
        self.assertEqual(sample.completeness_score, 96.54)
        self.assertEqual(sample.contamination_score, 0.08)
        self.assertEqual(sample.completeness_software, "CheckM2")
        self.assertIn("Created Sample SAMN40012083", out.getvalue())

        # Verify IngestVersion fields
        version = sample.ingest
        self.assertEqual(version.source_system, IngestVersion.SourceSystem.BIOSAMPLES)
        self.assertEqual(version.data_type, IngestVersion.DataType.SAMPLE_METADATA)
        self.assertEqual(version.pipeline_version, "custom_pipeline 2.0.0")
        self.assertEqual(version.release.label, "2.0")
        self.assertIsNotNone(version.retrieved_at)
        self.assertEqual(version.upstream_last_modified.year, 2025)
        self.assertEqual(version.upstream_last_modified.month, 1)
        self.assertEqual(version.upstream_last_modified.day, 22)

        # Verify ExternalResource was created
        ext = ExternalResource.objects.get(
            source_system=ExternalResource.SourceSystem.BIOSAMPLES,
            accession="SAMN40012083",
            ingest=version
        )
        self.assertEqual(ext.sample, sample)
        self.assertIsNone(ext.run)
        self.assertIsNone(ext.genome)
        self.assertEqual(ext.url, "https://www.ebi.ac.uk/biosamples/samples/SAMN40012083")

    @patch("samples.management.commands.ingest_sample.ena_api")
    @patch("samples.management.commands.ingest_sample.get_basic_sample_data")
    @patch("samples.management.commands.ingest_sample.curate_biosample")
    def test_ingest_sample_run_success(self, mock_curate, mock_get_data, mock_ena_api):
        """Test ingesting a run sample using real data snippets from SAMN39879075."""
        # Setup mocks
        mock_ena_api.get_all_accessions.return_value = {
            "ena_run": None,
            "ena_experiment": None,
            "biosample": "SAMN39879075",
            "ena_sample": "SRS20541912"
        }
        
        mock_get_data.return_value = {
            "name": "MFD13461",
            "accession": "SAMN39879075",
            "sraAccession": "SRS20541912",
            "update": "2024-12-01T10:00:00Z",
        }
        
        mock_curate.return_value = {
            "accession": "SAMN39879075",
            "latitude": 56.06193416,
            "longitude": 8.63495532,
            "geo_check_status": "PASS",
            "geo_check_reason": "match",
            "region": "Denmark",
            "locality": None,
            "biome": "Other;Urban;Biogas;Biogas unknown"
        }

        out = io.StringIO()
        call_command(
            "ingest_sample",
            accession="SAMN39879075",
            source="MFD",
            sample_type="run",
            version_label="test_v1",
            stdout=out
        )

        # Verify Sample was created
        sample = Sample.objects.get(biosample="SAMN39879075")
        self.assertEqual(sample.latitude, 56.06193416)
        self.assertEqual(sample.longitude, 8.63495532)
        self.assertEqual(sample.ontology, "Other;Urban;Biogas;Biogas unknown")
        self.assertIn("Created Sample SAMN39879075", out.getvalue())
        
        # Verify IngestVersion fields
        version = sample.ingest
        self.assertEqual(version.upstream_last_modified.year, 2024)
        self.assertEqual(version.upstream_last_modified.month, 12)
        self.assertEqual(version.upstream_last_modified.day, 1)

    @patch("samples.management.commands.ingest_sample.ena_api")
    def test_ingest_sample_ena_failure(self, mock_ena_api):
        mock_ena_api.get_all_accessions.side_effect = Exception("ENA error")

        with self.assertRaises(CommandError) as cm:
            call_command(
                "ingest_sample",
                accession="SAMN12345",
                source="MFD",
                version_label="test_v1"
            )
        self.assertIn("Failed to get accessions for SAMN12345: ENA error", str(cm.exception))

    @patch("samples.management.commands.ingest_sample.ena_api")
    @patch("samples.management.commands.ingest_sample.get_basic_sample_data")
    @patch("samples.management.commands.ingest_sample.curate_biosample")
    def test_ingest_sample_update(self, mock_curate, mock_get_data, mock_ena_api):
        # Create existing sample
        version = IngestVersion.objects.create(
            source_system=IngestVersion.SourceSystem.BIOSAMPLES,
            label="test_v1",
            data_type=IngestVersion.DataType.SAMPLE_METADATA
        )
        Sample.objects.create(
            biosample="SAMN12345",
            ena_sample="ERS12345",
            source_dataset="OLD",
            ingest=version
        )

        # Setup mocks
        mock_ena_api.get_all_accessions.return_value = {
            "biosample": "SAMN12345",
            "ena_sample": "ERS12345"
        }
        mock_get_data.return_value = {"raw": "data", "update": "2025-01-01T00:00:00Z"}
        mock_curate.return_value = {
            "latitude": 52.5,
            "longitude": 13.4,
            "region": "Europe",
            "locality": "Berlin",
            "geo_check_status": "PASS",
            "geo_check_reason": "match",
            "biome": "urban",
        }

        out = io.StringIO()
        call_command(
            "ingest_sample",
            accession="SAMN12345",
            source="MFD",
            version_label="test_v1",
            stdout=out
        )

        # Verify Sample was updated
        sample = Sample.objects.get(biosample="SAMN12345")
        self.assertEqual(sample.source_dataset, "MFD")
        self.assertEqual(sample.latitude, 52.5)
        self.assertIn("Updated Sample SAMN12345", out.getvalue())

    @patch("samples.management.commands.ingest_sample.ena_api")
    def test_ingest_sample_no_accession(self, mock_ena_api):
        mock_ena_api.get_all_accessions.return_value = {} # No accessions found

        with self.assertRaises(CommandError) as cm:
            call_command(
                "ingest_sample",
                accession="INVALID",
                source="MFD",
                version_label="test_v1"
            )
        self.assertIn("Could not find a valid sample accession for INVALID", str(cm.exception))

    @patch("samples.management.commands.ingest_sample.ena_api")
    @patch("samples.management.commands.ingest_sample.get_basic_sample_data")
    def test_ingest_sample_fetch_failure(self, mock_get_data, mock_ena_api):
        mock_ena_api.get_all_accessions.return_value = {"biosample": "SAMN12345"}
        mock_get_data.side_effect = Exception("Fetch error")

        with self.assertRaises(CommandError) as cm:
            call_command(
                "ingest_sample",
                accession="SAMN12345",
                source="MFD",
                version_label="test_v1"
            )
        self.assertIn("Failed to fetch BioSample SAMN12345: Fetch error", str(cm.exception))

    @patch("samples.management.commands.ingest_sample.ena_api")
    @patch("samples.management.commands.ingest_sample.get_basic_sample_data")
    @patch("samples.management.commands.ingest_sample.curate_biosample")
    def test_ingest_sample_curation_failure(self, mock_curate, mock_get_data, mock_ena_api):
        mock_ena_api.get_all_accessions.return_value = {"biosample": "SAMN12345"}
        mock_get_data.return_value = {"raw": "data"}
        mock_curate.side_effect = Exception("Curation error")

        with self.assertRaises(CommandError) as cm:
            call_command(
                "ingest_sample",
                accession="SAMN12345",
                source="MFD",
                version_label="test_v1"
            )
        self.assertIn("Failed to curate BioSample SAMN12345: Curation error", str(cm.exception))
