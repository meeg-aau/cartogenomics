from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from external.models import ExternalResource
from runs.models import Run
from samples.models import Sample, SampleVersion
from versions.models import IngestVersion


BIOSAMPLE_ACC = "SAMEA123456"
ENA_SAMPLE_ACC = "ERS123456"
RUN_ACC = "ERR123456"
FASTQ_FTP = "ftp.ebi.ac.uk/vol1/fastq/ERR123/ERR123456/ERR123456_1.fastq.gz"

RUNS_DATA = [{
    "run_accession": RUN_ACC,
    "biosample": BIOSAMPLE_ACC,
    "ena_sample": ENA_SAMPLE_ACC,
    "read_count": 1000000,
    "first_created": "2023-01-15T10:00:00Z",
    "last_updated": "2023-06-01T00:00:00Z",
    "fastq_ftp": FASTQ_FTP,
    "library_source": "METAGENOMIC",
    "library_strategy": "WGS",
    "instrument_model": "Illumina NovaSeq 6000",
    "instrument_platform": "ILLUMINA",
}]

RAW_DATA = {
    "accession": BIOSAMPLE_ACC,
    "submitted": "2022-06-01T00:00:00Z",
    "update": "2023-01-15T10:00:00Z",
}

CURATED_DATA = {
    "latitude": 56.0,
    "longitude": 9.0,
    "region": "Denmark",
    "locality": None,
    "geo_check_status": "PASS",
    "geo_check_reason": "match",
    "biome": "forest biome",
}


def _run_ingest(accession=BIOSAMPLE_ACC, source="MFD", version_label="mfd_test", **kwargs):
    call_command(
        "ingest_sample",
        accession=accession,
        source=source,
        version_label=version_label,
        **kwargs,
    )


def _patch_apis(runs_data=None, raw_data=None, curated_data=None):
    runs = runs_data if runs_data is not None else RUNS_DATA
    raw = raw_data if raw_data is not None else RAW_DATA
    curated = curated_data if curated_data is not None else CURATED_DATA

    return (
        patch("samples.management.commands.ingest_sample.ena_api.get_all_run_accessions", return_value=runs),
        patch("samples.management.commands.ingest_sample.get_basic_sample_data", return_value=raw),
        patch("samples.management.commands.ingest_sample.curate_biosample", return_value=curated),
    )


class SampleCreationTest(TestCase):
    """Sample, IngestVersion, and SampleVersion are correct after first ingest."""

    def setUp(self):
        ena_patch, bs_patch, curate_patch = _patch_apis()
        with ena_patch, bs_patch, curate_patch:
            _run_ingest(no_runs=True)
        self.sample = Sample.objects.get(biosample=BIOSAMPLE_ACC)

    def test_sample_curated_fields(self):
        self.assertEqual(self.sample.ena_sample, ENA_SAMPLE_ACC)
        self.assertEqual(self.sample.source_dataset, "MFD")
        self.assertEqual(self.sample.latitude, 56.0)
        self.assertEqual(self.sample.longitude, 9.0)
        self.assertEqual(self.sample.region, "Denmark")
        self.assertIsNone(self.sample.locality)
        self.assertEqual(self.sample.geography_check_status, "PASS")
        self.assertEqual(self.sample.geography_status_reason, "match")
        self.assertEqual(self.sample.ontology, "forest biome")

    def test_sample_archive_dates(self):
        self.assertIsNotNone(self.sample.archive_created)
        self.assertEqual(self.sample.archive_created.year, 2022)
        self.assertIsNotNone(self.sample.archive_updated)
        self.assertEqual(self.sample.archive_updated.year, 2023)

    def test_ingest_version(self):
        version = self.sample.ingest
        self.assertEqual(version.source_system, IngestVersion.SourceSystem.BIOSAMPLES)
        self.assertEqual(version.data_type, IngestVersion.DataType.SAMPLE_METADATA)
        self.assertEqual(version.label, "mfd_test")
        self.assertEqual(version.pipeline_version, "sample_metadata_curation 0.1.0")
        self.assertIsNotNone(version.ingested_on)

    def test_sample_version_created(self):
        versions = SampleVersion.objects.filter(sample=self.sample)
        self.assertEqual(versions.count(), 1)
        v = versions.first()
        self.assertIsNone(v.valid_to)
        self.assertEqual(v.latitude, 56.0)
        self.assertEqual(v.ontology, "forest biome")
        self.assertEqual(v.ingest, self.sample.ingest)

    def test_external_resource_for_sample(self):
        ext = ExternalResource.objects.get(
            source_system=ExternalResource.SourceSystem.BIOSAMPLES,
            sample=self.sample,
        )
        self.assertEqual(ext.url, f"https://www.ebi.ac.uk/biosamples/samples/{BIOSAMPLE_ACC}.json")
        self.assertIsNone(ext.run)
        self.assertIsNone(ext.genome)
        self.assertIsNotNone(ext.first_created_external)
        self.assertIsNotNone(ext.last_modified_external)


class RunCreationTest(TestCase):
    """Run and FASTQ ExternalResource rows are correct after ingest."""

    def setUp(self):
        ena_patch, bs_patch, curate_patch = _patch_apis()
        with ena_patch, bs_patch, curate_patch:
            _run_ingest()

    def test_run_created(self):
        run = Run.objects.get(accession=RUN_ACC)
        sample = Sample.objects.get(biosample=BIOSAMPLE_ACC)
        self.assertEqual(run.sample, sample)
        self.assertEqual(run.read_count, 1000000)
        self.assertEqual(run.sequencer, "Illumina NovaSeq 6000")
        self.assertEqual(run.library_source, "METAGENOMIC")
        self.assertEqual(run.library_strategy, "WGS")
        self.assertIsNotNone(run.archive_created)
        self.assertEqual(run.archive_created.year, 2023)

    def test_fastq_external_resource(self):
        run = Run.objects.get(accession=RUN_ACC)
        filename = FASTQ_FTP.split("/")[-1]
        ext = ExternalResource.objects.get(accession=filename)
        self.assertEqual(ext.run, run)
        self.assertEqual(ext.url, f"https://{FASTQ_FTP}")
        self.assertEqual(ext.source_system, ExternalResource.SourceSystem.ENA)
        self.assertIsNone(ext.sample)
        self.assertIsNone(ext.genome)

    def test_no_runs_flag_skips_runs(self):
        Run.objects.all().delete()
        ena_patch, bs_patch, curate_patch = _patch_apis()
        with ena_patch, bs_patch, curate_patch:
            _run_ingest(no_runs=True)
        self.assertEqual(Run.objects.count(), 0)
        self.assertEqual(
            ExternalResource.objects.filter(source_system=ExternalResource.SourceSystem.ENA).count(),
            0,
        )

    def test_run_not_duplicated_on_reingest(self):
        ena_patch, bs_patch, curate_patch = _patch_apis()
        with ena_patch, bs_patch, curate_patch:
            _run_ingest()
        self.assertEqual(Run.objects.filter(accession=RUN_ACC).count(), 1)


class SampleVersioningTest(TestCase):
    """SampleVersion history is correct across multiple ingests."""

    def _ingest(self, curated_data=None):
        ena_patch, bs_patch, curate_patch = _patch_apis(curated_data=curated_data)
        with ena_patch, bs_patch, curate_patch:
            _run_ingest(no_runs=True)

    def test_reingest_with_changed_field_creates_new_version(self):
        self._ingest()
        updated = {**CURATED_DATA, "region": "Sweden"}
        self._ingest(curated_data=updated)

        sample = Sample.objects.get(biosample=BIOSAMPLE_ACC)
        self.assertEqual(sample.region, "Sweden")

        versions = SampleVersion.objects.filter(sample=sample).order_by("valid_from")
        self.assertEqual(versions.count(), 2)
        self.assertIsNotNone(versions[0].valid_to)
        self.assertIsNone(versions[1].valid_to)
        self.assertEqual(versions[1].region, "Sweden")

    def test_reingest_with_no_changes_does_not_create_new_version(self):
        self._ingest()
        self._ingest()

        sample = Sample.objects.get(biosample=BIOSAMPLE_ACC)
        self.assertEqual(SampleVersion.objects.filter(sample=sample).count(), 1)

    def test_only_one_open_version_at_any_time(self):
        self._ingest()
        self._ingest(curated_data={**CURATED_DATA, "region": "Sweden"})
        self._ingest(curated_data={**CURATED_DATA, "region": "Norway"})

        sample = Sample.objects.get(biosample=BIOSAMPLE_ACC)
        open_versions = SampleVersion.objects.filter(sample=sample, valid_to__isnull=True)
        self.assertEqual(open_versions.count(), 1)
        self.assertEqual(open_versions.first().region, "Norway")

    def test_archive_dates_not_in_sample_version(self):
        self._ingest()
        sample = Sample.objects.get(biosample=BIOSAMPLE_ACC)
        version = SampleVersion.objects.get(sample=sample)
        self.assertFalse(hasattr(version, "archive_created"))
        self.assertFalse(hasattr(version, "archive_updated"))


class ErrorHandlingTest(TestCase):
    """Command fails cleanly when API calls fail."""

    def test_ena_api_failure_raises_command_error(self):
        with patch("samples.management.commands.ingest_sample.ena_api.get_all_run_accessions", side_effect=Exception("ENA down")):
            with self.assertRaises(CommandError) as cm:
                _run_ingest()
        self.assertIn("Failed to get accessions", str(cm.exception))

    def test_biosample_fetch_failure_raises_command_error(self):
        ena_patch = patch("samples.management.commands.ingest_sample.ena_api.get_all_run_accessions", return_value=RUNS_DATA)
        bs_patch = patch("samples.management.commands.ingest_sample.get_basic_sample_data", side_effect=Exception("timeout"))
        with ena_patch, bs_patch:
            with self.assertRaises(CommandError) as cm:
                _run_ingest()
        self.assertIn("Failed to fetch BioSample", str(cm.exception))

    def test_curation_failure_raises_command_error(self):
        ena_patch = patch("samples.management.commands.ingest_sample.ena_api.get_all_run_accessions", return_value=RUNS_DATA)
        bs_patch = patch("samples.management.commands.ingest_sample.get_basic_sample_data", return_value=RAW_DATA)
        curate_patch = patch("samples.management.commands.ingest_sample.curate_biosample", side_effect=Exception("bad data"))
        with ena_patch, bs_patch, curate_patch:
            with self.assertRaises(CommandError) as cm:
                _run_ingest()
        self.assertIn("Failed to curate BioSample", str(cm.exception))

    def test_no_data_returned_raises_command_error(self):
        ena_patch = patch("samples.management.commands.ingest_sample.ena_api.get_all_run_accessions", return_value=[])
        with ena_patch:
            with self.assertRaises(CommandError):
                _run_ingest()
