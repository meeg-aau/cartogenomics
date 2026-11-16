from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from external.models import ExternalResource
from genomes.models import Genome, GenomeVersion
from versions.models import IngestVersion

GENOME_ACC = "GCA_123456789.1"
BIOSAMPLE_ACC = "SAMEA123456"
ENA_SAMPLE_ACC = "ERS123456"
FASTA_FTP = "ftp.ebi.ac.uk/pub/databases/ena/wgs/public/abc/ABCD01.fasta.gz"

GET_ALL_GENOME_ACCESSIONS = (
    "genomes.management.commands.ingest_genome.ena_api.get_all_genome_accessions"
)

ACCESSIONS = {
    "genome_accession": GENOME_ACC,
    "biosample": BIOSAMPLE_ACC,
    "ena_sample": ENA_SAMPLE_ACC,
    "first_created": "2022-03-01T00:00:00Z",
    "last_updated": "2023-06-15T00:00:00Z",
    "set_fasta_ftp": FASTA_FTP,
}

RAW_DATA = {
    "accession": BIOSAMPLE_ACC,
    "submitted": "2022-03-01T00:00:00Z",
    "update": "2023-06-15T00:00:00Z",
}

CURATED_DATA = {
    "completeness_score": 95.5,
    "contamination_score": 0.5,
    "completeness_software": "checkm2",
}


def _run_ingest(
    accession=GENOME_ACC, source="GTDB", version_label="gtdb_test", **kwargs
):
    call_command(
        "ingest_genome",
        accession=accession,
        source=source,
        version_label=version_label,
        **kwargs,
    )


def _patch_apis(accessions=None, raw_data=None, curated_data=None):
    accs = accessions if accessions is not None else ACCESSIONS
    raw = raw_data if raw_data is not None else RAW_DATA
    curated = curated_data if curated_data is not None else CURATED_DATA

    return (
        patch(
            GET_ALL_GENOME_ACCESSIONS,
            return_value=accs,
        ),
        patch(
            "genomes.management.commands.ingest_genome.get_basic_sample_data",
            return_value=raw,
        ),
        patch(
            "genomes.management.commands.ingest_genome.curate_biosample",
            return_value=curated,
        ),
    )


class GenomeCreationTest(TestCase):
    """Genome, IngestVersion, and GenomeVersion are correct after first ingest."""

    def setUp(self):
        ena_patch, bs_patch, curate_patch = _patch_apis()
        with ena_patch, bs_patch, curate_patch:
            _run_ingest()
        self.genome = Genome.objects.get(accession=GENOME_ACC)

    def test_genome_curated_fields(self):
        self.assertEqual(self.genome.completeness, 95.5)
        self.assertEqual(self.genome.contamination, 0.5)
        self.assertEqual(self.genome.completeness_software, "checkm2")

    def test_genome_archive_dates(self):
        self.assertIsNotNone(self.genome.archive_created)
        self.assertEqual(self.genome.archive_created.year, 2022)
        self.assertIsNotNone(self.genome.archive_updated)
        self.assertEqual(self.genome.archive_updated.year, 2023)

    def test_ingest_version(self):
        version = self.genome.ingest
        self.assertEqual(version.source_system, IngestVersion.SourceSystem.ENA)
        self.assertEqual(version.data_type, IngestVersion.DataType.GENOMES)
        self.assertEqual(version.label, "gtdb_test")
        self.assertIsNotNone(version.ingested_on)

    def test_genome_version_created(self):
        versions = GenomeVersion.objects.filter(genome=self.genome)
        self.assertEqual(versions.count(), 1)
        v = versions.first()
        self.assertIsNone(v.valid_to)
        self.assertEqual(v.completeness, 95.5)
        self.assertEqual(v.ingest, self.genome.ingest)

    def test_fasta_external_resource(self):
        ext = ExternalResource.objects.get(
            source_system=ExternalResource.SourceSystem.ENA,
            accession=GENOME_ACC,
        )
        self.assertEqual(ext.genome, self.genome)
        self.assertEqual(ext.url, f"https://{FASTA_FTP}")
        self.assertIsNone(ext.sample)
        self.assertIsNone(ext.run)
        self.assertIsNotNone(ext.first_created_external)
        self.assertIsNotNone(ext.last_modified_external)

    def test_no_fasta_external_resource_when_ftp_missing(self):
        accs_no_fasta = {**ACCESSIONS, "set_fasta_ftp": None}
        ena_patch, bs_patch, curate_patch = _patch_apis(accessions=accs_no_fasta)
        Genome.objects.all().delete()
        with ena_patch, bs_patch, curate_patch:
            _run_ingest()
        self.assertFalse(
            ExternalResource.objects.filter(
                source_system=ExternalResource.SourceSystem.ENA,
                accession=GENOME_ACC,
            ).exists()
        )


class GenomeVersioningTest(TestCase):
    """GenomeVersion history is correct across multiple ingests."""

    def _ingest(self, curated_data=None):
        ena_patch, bs_patch, curate_patch = _patch_apis(curated_data=curated_data)
        with ena_patch, bs_patch, curate_patch:
            _run_ingest()

    def test_reingest_with_changed_field_creates_new_version(self):
        self._ingest()
        self._ingest(curated_data={**CURATED_DATA, "completeness_score": 97.0})

        genome = Genome.objects.get(accession=GENOME_ACC)
        self.assertEqual(genome.completeness, 97.0)

        versions = GenomeVersion.objects.filter(genome=genome).order_by("valid_from")
        self.assertEqual(versions.count(), 2)
        self.assertIsNotNone(versions[0].valid_to)
        self.assertIsNone(versions[1].valid_to)
        self.assertEqual(versions[1].completeness, 97.0)

    def test_reingest_with_no_changes_does_not_create_new_version(self):
        self._ingest()
        self._ingest()

        genome = Genome.objects.get(accession=GENOME_ACC)
        self.assertEqual(GenomeVersion.objects.filter(genome=genome).count(), 1)

    def test_only_one_open_version_at_any_time(self):
        self._ingest()
        self._ingest(curated_data={**CURATED_DATA, "completeness_score": 97.0})
        self._ingest(curated_data={**CURATED_DATA, "completeness_score": 98.0})

        genome = Genome.objects.get(accession=GENOME_ACC)
        open_versions = GenomeVersion.objects.filter(
            genome=genome, valid_to__isnull=True
        )
        self.assertEqual(open_versions.count(), 1)
        self.assertEqual(open_versions.first().completeness, 98.0)


class ErrorHandlingTest(TestCase):
    """Command fails cleanly when API calls fail."""

    def test_ena_api_failure_raises_command_error(self):
        with patch(
            GET_ALL_GENOME_ACCESSIONS,
            side_effect=Exception("ENA down"),
        ):
            with self.assertRaises(CommandError) as cm:
                _run_ingest()
        self.assertIn("Failed to get genome accessions", str(cm.exception))

    def test_no_genome_accession_raises_command_error(self):
        accs_no_genome = {**ACCESSIONS, "genome_accession": None}
        with patch(
            GET_ALL_GENOME_ACCESSIONS,
            return_value=accs_no_genome,
        ):
            with self.assertRaises(CommandError) as cm:
                _run_ingest()
        self.assertIn("No genome accession found", str(cm.exception))

    def test_biosample_fetch_failure_raises_command_error(self):
        ena_patch = patch(
            GET_ALL_GENOME_ACCESSIONS,
            return_value=ACCESSIONS,
        )
        bs_patch = patch(
            "genomes.management.commands.ingest_genome.get_basic_sample_data",
            side_effect=Exception("timeout"),
        )
        with ena_patch, bs_patch:
            with self.assertRaises(CommandError) as cm:
                _run_ingest()
        self.assertIn("Failed to fetch BioSample", str(cm.exception))

    def test_curation_failure_raises_command_error(self):
        ena_patch = patch(
            GET_ALL_GENOME_ACCESSIONS,
            return_value=ACCESSIONS,
        )
        bs_patch = patch(
            "genomes.management.commands.ingest_genome.get_basic_sample_data",
            return_value=RAW_DATA,
        )
        curate_patch = patch(
            "genomes.management.commands.ingest_genome.curate_biosample",
            side_effect=Exception("bad data"),
        )
        with ena_patch, bs_patch, curate_patch:
            with self.assertRaises(CommandError) as cm:
                _run_ingest()
        self.assertIn("Failed to curate BioSample", str(cm.exception))
