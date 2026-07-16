from django.contrib.gis.geos import MultiPolygon, Point, Polygon
from django.test import TestCase

from external.models import ExternalResource
from genomes.models import Genome
from regions.models import CountryBoundary
from rocrates.builder import build_crate
from runs.models import Run
from samples.models import Sample
from versions.models import CartogenomicsRelease, IngestVersion


class BuildCrateTest(TestCase):
    """Tests for rocrates.builder.build_crate()."""

    def setUp(self):
        self.release = CartogenomicsRelease.objects.create(label="1.0")

        self.sample_ingest = IngestVersion.objects.create(
            source_system=IngestVersion.SourceSystem.BIOSAMPLES,
            data_type=IngestVersion.DataType.SAMPLE_METADATA,
            label="test_sample_ingest",
            release=self.release,
        )
        self.genome_ingest = IngestVersion.objects.create(
            source_system=IngestVersion.SourceSystem.ENA,
            data_type=IngestVersion.DataType.GENOMES,
            label="test_genome_ingest",
            release=self.release,
        )

    def _make_sample(self, biosample="SAMEA001", ena_sample="ERS001", **kwargs):
        defaults = dict(
            biosample=biosample,
            ena_sample=ena_sample,
            source_dataset="MFD",
            ingest=self.sample_ingest,
            latitude=55.0,
            longitude=10.0,
            ontology="forest biome",
            region="Denmark",
        )
        defaults.update(kwargs)
        #   mirror ingest_sample.py: location is derived from lat/lon unless
        #   explicitly overridden, so spatial filters have something to match
        if (
            "location" not in defaults
            and defaults.get("latitude") is not None
            and defaults.get("longitude") is not None
        ):
            defaults["location"] = Point(
                defaults["longitude"], defaults["latitude"], srid=4326
            )
        return Sample.objects.create(**defaults)

    def _make_genome(self, accession="GCA_001", **kwargs):
        defaults = dict(
            accession=accession,
            ingest=self.genome_ingest,
            completeness=95.0,
            contamination=1.5,
            completeness_software=Genome.CompletenessSoftware.CHECKM2,
            taxonomy="d__Bacteria;p__Firmicutes",
            genome_size=3000000,
            n50=50000,
        )
        defaults.update(kwargs)
        return Genome.objects.create(**defaults)

    def _make_run(self, sample, accession="ERR001", **kwargs):
        defaults = dict(
            accession=accession,
            sample=sample,
            ingest=self.sample_ingest,
            read_count=1000000,
            sequencer="Illumina NovaSeq 6000",
        )
        defaults.update(kwargs)
        return Run.objects.create(**defaults)

    def _make_external(self, url, *, sample=None, genome=None, run=None):
        return ExternalResource.objects.create(
            source_system=ExternalResource.SourceSystem.ENA,
            accession=url.split("/")[-1],
            url=url,
            ingest=self.sample_ingest,
            sample=sample,
            genome=genome,
            run=run,
        )

    def test_root_metadata_label_uses_filters(self):
        crate = build_crate(source_dataset="MFD", release_label="1.0")
        self.assertIn("MFD", crate.root_dataset["name"])
        self.assertIn("release:1.0", crate.root_dataset["name"])

    def test_root_metadata_custom_label(self):
        crate = build_crate(label="My custom export")
        self.assertEqual(crate.root_dataset["name"], "My custom export")

    def test_root_metadata_date_published_set(self):
        from datetime import date

        crate = build_crate()
        self.assertEqual(crate.root_dataset["datePublished"], str(date.today()))

    def test_root_metadata_spatial_coverage_set_when_bbox_given(self):
        crate = build_crate(lat_min=54.0, lat_max=58.0, lon_min=8.0, lon_max=15.0)
        self.assertIn("spatialCoverage", crate.root_dataset)

    def test_root_metadata_no_spatial_coverage_without_bbox(self):
        crate = build_crate()
        self.assertNotIn("spatialCoverage", crate.root_dataset)

    def test_root_metadata_label_includes_country_code(self):
        denmark = Polygon(
            ((8.0, 54.5), (8.0, 57.7), (12.7, 57.7), (12.7, 54.5), (8.0, 54.5))
        )
        CountryBoundary.objects.create(
            iso_two_cc="DK", name="Denmark", geom=MultiPolygon(denmark)
        )
        crate = build_crate(country_code="dk")
        self.assertIn("country:DK", crate.root_dataset["name"])
        self.assertEqual(crate.root_dataset["exportFilters"]["countryCode"], "DK")

    def test_root_metadata_filters_include_polygon(self):
        polygon_wkt = "POLYGON((5 50, 5 60, 15 60, 15 50, 5 50))"
        crate = build_crate(polygon=polygon_wkt)
        self.assertEqual(crate.root_dataset["exportFilters"]["polygon"], polygon_wkt)

    # ------------------------------------------------------------------
    # Sample entities
    # ------------------------------------------------------------------

    def test_sample_entity_created(self):
        self._make_sample()
        crate = build_crate()
        entity = crate.get("#sample-SAMEA001")
        self.assertIsNotNone(entity)

    def test_sample_entity_properties(self):
        self._make_sample(
            biosample="SAMEA002", ontology="grassland biome", region="Germany"
        )
        crate = build_crate()
        entity = crate.get("#sample-SAMEA002")
        self.assertEqual(entity["environmentType"], "grassland biome")
        self.assertEqual(entity["addressRegion"], "Germany")
        self.assertIn("SAMEA002", entity["identifier"])

    def test_sample_entity_geography_fields(self):
        self._make_sample(latitude=56.1, longitude=9.5)
        crate = build_crate()
        entity = crate.get("#sample-SAMEA001")
        self.assertEqual(entity["latitude"], 56.1)
        self.assertEqual(entity["longitude"], 9.5)

    def test_multiple_samples_all_included(self):
        self._make_sample(biosample="SAMEA001", ena_sample="ERS001")
        self._make_sample(biosample="SAMEA002", ena_sample="ERS002")
        crate = build_crate()
        self.assertIsNotNone(crate.get("#sample-SAMEA001"))
        self.assertIsNotNone(crate.get("#sample-SAMEA002"))

    # ------------------------------------------------------------------
    # Sample filters
    # ------------------------------------------------------------------

    def test_filter_by_source_dataset(self):
        self._make_sample(
            biosample="SAMEA001", ena_sample="ERS001", source_dataset="MFD"
        )
        self._make_sample(
            biosample="SAMEA002", ena_sample="ERS002", source_dataset="GTDB"
        )
        crate = build_crate(source_dataset="MFD")
        self.assertIsNotNone(crate.get("#sample-SAMEA001"))
        self.assertIsNone(crate.get("#sample-SAMEA002"))

    def test_filter_by_ontology_substring(self):
        self._make_sample(
            biosample="SAMEA001", ena_sample="ERS001", ontology="forest biome"
        )
        self._make_sample(
            biosample="SAMEA002", ena_sample="ERS002", ontology="marine biome"
        )
        crate = build_crate(ontology="forest")
        self.assertIsNotNone(crate.get("#sample-SAMEA001"))
        self.assertIsNone(crate.get("#sample-SAMEA002"))

    def test_filter_by_lat_lon_bbox(self):
        self._make_sample(
            biosample="SAMEA001", ena_sample="ERS001", latitude=55.0, longitude=10.0
        )
        self._make_sample(
            biosample="SAMEA002", ena_sample="ERS002", latitude=40.0, longitude=2.0
        )
        crate = build_crate(lat_min=50.0, lat_max=60.0, lon_min=5.0, lon_max=15.0)
        self.assertIsNotNone(crate.get("#sample-SAMEA001"))
        self.assertIsNone(crate.get("#sample-SAMEA002"))

    def test_filter_by_radius(self):
        self._make_sample(
            biosample="SAMEA001", ena_sample="ERS001", latitude=55.68, longitude=12.57
        )  # Copenhagen
        self._make_sample(
            biosample="SAMEA002", ena_sample="ERS002", latitude=48.86, longitude=2.35
        )  # Paris
        crate = build_crate(near_lat=55.68, near_lon=12.57, radius_km=50)
        self.assertIsNotNone(crate.get("#sample-SAMEA001"))
        self.assertIsNone(crate.get("#sample-SAMEA002"))

    def test_filter_by_country_code(self):
        denmark = Polygon(
            ((8.0, 54.5), (8.0, 57.7), (12.7, 57.7), (12.7, 54.5), (8.0, 54.5))
        )
        CountryBoundary.objects.create(
            iso_two_cc="DK", name="Denmark", geom=MultiPolygon(denmark)
        )
        self._make_sample(
            biosample="SAMEA001", ena_sample="ERS001", latitude=55.68, longitude=12.57
        )  # Copenhagen
        self._make_sample(
            biosample="SAMEA002", ena_sample="ERS002", latitude=48.86, longitude=2.35
        )  # Paris
        crate = build_crate(country_code="dk")
        self.assertIsNotNone(crate.get("#sample-SAMEA001"))
        self.assertIsNone(crate.get("#sample-SAMEA002"))

    def test_filter_by_unknown_country_code_raises(self):
        with self.assertRaises(ValueError):
            build_crate(country_code="ZZ")

    def test_bbox_and_radius_together_raises(self):
        with self.assertRaises(ValueError):
            build_crate(
                lat_min=50.0,
                lat_max=60.0,
                lon_min=5.0,
                lon_max=15.0,
                near_lat=55.0,
                near_lon=10.0,
                radius_km=50,
            )

    def test_bbox_and_country_code_together_raises(self):
        denmark = Polygon(
            ((8.0, 54.5), (8.0, 57.7), (12.7, 57.7), (12.7, 54.5), (8.0, 54.5))
        )
        CountryBoundary.objects.create(
            iso_two_cc="DK", name="Denmark", geom=MultiPolygon(denmark)
        )
        with self.assertRaises(ValueError):
            build_crate(
                lat_min=50.0, lat_max=60.0, lon_min=5.0, lon_max=15.0, country_code="DK"
            )

    def test_polygon_and_country_code_together_raises(self):
        denmark = Polygon(
            ((8.0, 54.5), (8.0, 57.7), (12.7, 57.7), (12.7, 54.5), (8.0, 54.5))
        )
        CountryBoundary.objects.create(
            iso_two_cc="DK", name="Denmark", geom=MultiPolygon(denmark)
        )
        with self.assertRaises(ValueError):
            build_crate(
                polygon="POLYGON((5 50, 5 60, 15 60, 15 50, 5 50))", country_code="DK"
            )

    def test_non_spatial_filters_still_combine_with_one_location_filter(self):
        """source_dataset/ontology/release_label aren't part of the
        mutual-exclusivity rule."""
        self._make_sample(
            biosample="SAMEA001",
            ena_sample="ERS001",
            latitude=55.0,
            longitude=10.0,
            source_dataset="MFD",
        )
        self._make_sample(
            biosample="SAMEA002",
            ena_sample="ERS002",
            latitude=55.0,
            longitude=10.0,
            source_dataset="GTDB",
        )
        crate = build_crate(
            lat_min=50.0, lat_max=60.0, lon_min=5.0, lon_max=15.0, source_dataset="MFD"
        )
        self.assertIsNotNone(crate.get("#sample-SAMEA001"))
        self.assertIsNone(crate.get("#sample-SAMEA002"))

    def test_filter_by_custom_polygon_wkt(self):
        self._make_sample(
            biosample="SAMEA001", ena_sample="ERS001", latitude=55.0, longitude=10.0
        )
        self._make_sample(
            biosample="SAMEA002", ena_sample="ERS002", latitude=40.0, longitude=2.0
        )
        polygon_wkt = "POLYGON((5 50, 5 60, 15 60, 15 50, 5 50))"
        crate = build_crate(polygon=polygon_wkt)
        self.assertIsNotNone(crate.get("#sample-SAMEA001"))
        self.assertIsNone(crate.get("#sample-SAMEA002"))

    def test_filter_by_release_label(self):
        other_release = CartogenomicsRelease.objects.create(label="2.0")
        other_ingest = IngestVersion.objects.create(
            source_system=IngestVersion.SourceSystem.BIOSAMPLES,
            data_type=IngestVersion.DataType.SAMPLE_METADATA,
            label="other_ingest",
            release=other_release,
        )
        self._make_sample(biosample="SAMEA001", ena_sample="ERS001")  # release 1.0
        Sample.objects.create(
            biosample="SAMEA002",
            ena_sample="ERS002",
            source_dataset="MFD",
            ingest=other_ingest,
        )
        crate = build_crate(release_label="1.0")
        self.assertIsNotNone(crate.get("#sample-SAMEA001"))
        self.assertIsNone(crate.get("#sample-SAMEA002"))

    def test_include_samples_false_excludes_all_samples(self):
        self._make_sample()
        crate = build_crate(include_samples=False)
        self.assertIsNone(crate.get("#sample-SAMEA001"))

    def test_empty_queryset_produces_valid_crate(self):
        crate = build_crate(source_dataset="NONEXISTENT")
        self.assertIsNotNone(crate.root_dataset)
        self.assertEqual(
            len([e for e in crate.contextual_entities if e.id.startswith("#sample-")]),
            0,
        )

    # ------------------------------------------------------------------
    # Run entities
    # ------------------------------------------------------------------

    def test_run_entity_created(self):
        sample = self._make_sample()
        self._make_run(sample)
        crate = build_crate()
        self.assertIsNotNone(crate.get("#run-ERR001"))

    def test_run_entity_links_to_sample(self):
        sample = self._make_sample()
        self._make_run(sample)
        crate = build_crate()
        run_entity = crate.get("#run-ERR001")
        self.assertEqual(run_entity["sample"]["@id"], "#sample-SAMEA001")

    def test_run_entity_properties(self):
        sample = self._make_sample()
        self._make_run(sample, sequencer="Illumina NovaSeq 6000", read_count=500_000)
        crate = build_crate()
        run_entity = crate.get("#run-ERR001")
        self.assertEqual(run_entity["instrument"], "Illumina NovaSeq 6000")
        self.assertEqual(run_entity["contentSize"], 500_000)

    def test_include_runs_false_excludes_runs(self):
        sample = self._make_sample()
        self._make_run(sample)
        crate = build_crate(include_runs=False)
        self.assertIsNone(crate.get("#run-ERR001"))

    def test_runs_excluded_when_samples_excluded(self):
        sample = self._make_sample()
        self._make_run(sample)
        crate = build_crate(include_samples=False)
        self.assertIsNone(crate.get("#run-ERR001"))

    # ------------------------------------------------------------------
    # Genome entities
    # ------------------------------------------------------------------

    def test_genomes_excluded_by_default(self):
        self._make_genome()
        crate = build_crate()
        self.assertIsNone(crate.get("#genome-GCA_001"))

    def test_genome_entity_created(self):
        self._make_genome()
        crate = build_crate(include_genomes=True)
        self.assertIsNotNone(crate.get("#genome-GCA_001"))

    def test_genome_entity_properties(self):
        self._make_genome(
            completeness=97.5,
            contamination=0.5,
            taxonomy="d__Bacteria;p__Firmicutes",
            genome_size=3_500_000,
            n50=75_000,
        )
        crate = build_crate(include_genomes=True)
        entity = crate.get("#genome-GCA_001")
        self.assertEqual(entity["completeness"], 97.5)
        self.assertEqual(entity["contamination"], 0.5)
        self.assertEqual(entity["taxonomicRange"], "d__Bacteria;p__Firmicutes")
        self.assertEqual(entity["contentSize"], 3_500_000)
        self.assertEqual(entity["n50"], 75_000)

    def test_genome_filter_by_release(self):
        other_release = CartogenomicsRelease.objects.create(label="2.0")
        other_ingest = IngestVersion.objects.create(
            source_system=IngestVersion.SourceSystem.ENA,
            data_type=IngestVersion.DataType.GENOMES,
            label="other_genome_ingest",
            release=other_release,
        )
        self._make_genome(accession="GCA_001")  # release 1.0
        Genome.objects.create(
            accession="GCA_002",
            ingest=other_ingest,
            completeness=90.0,
            contamination=2.0,
        )
        crate = build_crate(include_genomes=True, genome_release_label="1.0")
        self.assertIsNotNone(crate.get("#genome-GCA_001"))
        self.assertIsNone(crate.get("#genome-GCA_002"))

    def test_genome_filter_by_min_completeness(self):
        self._make_genome(accession="GCA_HQ", completeness=95.0)
        self._make_genome(accession="GCA_LQ", completeness=50.0)
        crate = build_crate(include_genomes=True, min_completeness=80.0)
        self.assertIsNotNone(crate.get("#genome-GCA_HQ"))
        self.assertIsNone(crate.get("#genome-GCA_LQ"))

    def test_genome_filter_by_max_contamination(self):
        self._make_genome(accession="GCA_CLEAN", contamination=1.0)
        self._make_genome(accession="GCA_DIRTY", contamination=20.0)
        crate = build_crate(include_genomes=True, max_contamination=5.0)
        self.assertIsNotNone(crate.get("#genome-GCA_CLEAN"))
        self.assertIsNone(crate.get("#genome-GCA_DIRTY"))

    def test_genomes_independent_of_samples(self):
        """Genomes and samples are filtered independently — no cross-dependency."""
        self._make_sample()
        self._make_genome()
        crate = build_crate(
            source_dataset="MFD",
            include_genomes=True,
            genome_release_label="1.0",
        )
        self.assertIsNotNone(crate.get("#sample-SAMEA001"))
        self.assertIsNotNone(crate.get("#genome-GCA_001"))

    # ------------------------------------------------------------------
    # External resources (URL references)
    # ------------------------------------------------------------------

    def test_sample_external_resource_added_as_file(self):
        sample = self._make_sample()
        self._make_external("https://ena.ebi.ac.uk/files/sample.fasta", sample=sample)
        crate = build_crate()
        file_entity = crate.get("https://ena.ebi.ac.uk/files/sample.fasta")
        self.assertIsNotNone(file_entity)

    def test_run_external_resource_added_as_file(self):
        sample = self._make_sample()
        run = self._make_run(sample)
        self._make_external("https://ena.ebi.ac.uk/files/run.fastq.gz", run=run)
        crate = build_crate()
        file_entity = crate.get("https://ena.ebi.ac.uk/files/run.fastq.gz")
        self.assertIsNotNone(file_entity)

    def test_genome_external_resource_added_as_file(self):
        genome = self._make_genome()
        self._make_external("https://ena.ebi.ac.uk/files/genome.fasta", genome=genome)
        crate = build_crate(include_genomes=True)
        file_entity = crate.get("https://ena.ebi.ac.uk/files/genome.fasta")
        self.assertIsNotNone(file_entity)

    def test_parquet_external_resource_skipped(self):
        sample = self._make_sample()
        self._make_external(
            "https://biostudies.ebi.ac.uk/data/abundance.parquet", sample=sample
        )
        crate = build_crate()
        self.assertIsNone(
            crate.get("https://biostudies.ebi.ac.uk/data/abundance.parquet")
        )

    def test_media_type_set_for_fasta(self):
        sample = self._make_sample()
        self._make_external("https://ena.ebi.ac.uk/files/genome.fasta", sample=sample)
        crate = build_crate()
        entity = crate.get("https://ena.ebi.ac.uk/files/genome.fasta")
        self.assertEqual(entity["encodingFormat"], "text/x-fasta")

    def test_media_type_set_for_fastq_gz(self):
        sample = self._make_sample()
        self._make_external("https://ena.ebi.ac.uk/files/reads.fastq.gz", sample=sample)
        crate = build_crate()
        entity = crate.get("https://ena.ebi.ac.uk/files/reads.fastq.gz")
        self.assertEqual(entity["encodingFormat"], "application/gzip")

    # ------------------------------------------------------------------
    # Provenance — IngestVersion / pipeline / release
    # ------------------------------------------------------------------

    def test_ingest_action_entity_created(self):
        self._make_sample()
        crate = build_crate()
        ingest_id = "#ingest-biosamples-sample_metadata-test_sample_ingest"
        self.assertIsNotNone(crate.get(ingest_id))

    def test_ingest_action_has_end_time(self):
        from django.utils import timezone as tz

        self.sample_ingest.retrieved_at = tz.now()
        self.sample_ingest.save()
        self._make_sample()
        crate = build_crate()
        entity = crate.get("#ingest-biosamples-sample_metadata-test_sample_ingest")
        self.assertIn("endTime", entity)

    def test_pipeline_entity_created_when_pipeline_version_set(self):
        self.sample_ingest.pipeline_version = "sample_metadata_curation 0.1.0"
        self.sample_ingest.save()
        self._make_sample()
        crate = build_crate()
        entity = crate.get("#pipeline-sample_metadata_curation-0.1.0")
        self.assertIsNotNone(entity)
        self.assertEqual(entity["name"], "sample_metadata_curation")
        self.assertEqual(entity["softwareVersion"], "0.1.0")

    def test_pipeline_entity_not_duplicated_across_samples(self):
        self.sample_ingest.pipeline_version = "sample_metadata_curation 0.1.0"
        self.sample_ingest.save()
        self._make_sample(biosample="SAMEA001", ena_sample="ERS001")
        self._make_sample(biosample="SAMEA002", ena_sample="ERS002")
        crate = build_crate()
        pipeline_id = "#pipeline-sample_metadata_curation-0.1.0"
        matches = [e for e in crate.contextual_entities if e.id == pipeline_id]
        self.assertEqual(len(matches), 1)

    def test_ingest_entity_not_duplicated_across_samples(self):
        self._make_sample(biosample="SAMEA001", ena_sample="ERS001")
        self._make_sample(biosample="SAMEA002", ena_sample="ERS002")
        crate = build_crate()
        ingest_id = "#ingest-biosamples-sample_metadata-test_sample_ingest"
        matches = [e for e in crate.contextual_entities if e.id == ingest_id]
        self.assertEqual(len(matches), 1)

    def test_release_entity_created(self):
        self._make_sample()
        crate = build_crate(release_label="1.0")
        self.assertIsNotNone(crate.get("#release-1.0"))

    def test_release_entity_has_date_created(self):
        self._make_sample()
        crate = build_crate(release_label="1.0")
        entity = crate.get("#release-1.0")
        self.assertIn("dateCreated", entity)

    def test_sample_links_to_ingest_via_was_generated_by(self):
        self._make_sample()
        crate = build_crate()
        sample_entity = crate.get("#sample-SAMEA001")
        self.assertEqual(
            sample_entity["wasGeneratedBy"]["@id"],
            "#ingest-biosamples-sample_metadata-test_sample_ingest",
        )

    def test_run_links_to_ingest_via_was_generated_by(self):
        sample = self._make_sample()
        self._make_run(sample)
        crate = build_crate()
        run_entity = crate.get("#run-ERR001")
        self.assertIn("wasGeneratedBy", run_entity)

    def test_genome_links_to_ingest_via_was_generated_by(self):
        self._make_genome()
        crate = build_crate(include_genomes=True)
        genome_entity = crate.get("#genome-GCA_001")
        self.assertEqual(
            genome_entity["wasGeneratedBy"]["@id"],
            "#ingest-ena-genome-test_genome_ingest",
        )

    def test_export_action_always_present(self):
        crate = build_crate()
        self.assertIsNotNone(crate.get("#export"))

    def test_export_action_has_end_time(self):
        crate = build_crate()
        self.assertIn("endTime", crate.get("#export"))

    def test_cartogenomics_db_entity_always_present(self):
        crate = build_crate()
        self.assertIsNotNone(crate.get("#cartogenomics-db"))

    def test_root_dataset_links_to_export_action(self):
        crate = build_crate()
        self.assertEqual(crate.root_dataset["wasGeneratedBy"]["@id"], "#export")

    def test_root_dataset_links_to_release_when_scoped(self):
        self._make_sample()
        crate = build_crate(release_label="1.0")
        self.assertEqual(crate.root_dataset["isPartOf"]["@id"], "#release-1.0")

    # ------------------------------------------------------------------
    # External resource dates
    # ------------------------------------------------------------------

    def test_external_file_date_created_set(self):
        from django.utils import timezone as tz

        sample = self._make_sample()
        ext = self._make_external(
            "https://ena.ebi.ac.uk/files/sample.fasta", sample=sample
        )
        ext.first_created_external = tz.now()
        ext.save()
        crate = build_crate()
        entity = crate.get("https://ena.ebi.ac.uk/files/sample.fasta")
        self.assertIn("dateCreated", entity)

    def test_external_file_date_modified_set(self):
        from django.utils import timezone as tz

        sample = self._make_sample()
        ext = self._make_external(
            "https://ena.ebi.ac.uk/files/sample.fasta", sample=sample
        )
        ext.last_modified_external = tz.now()
        ext.save()
        crate = build_crate()
        entity = crate.get("https://ena.ebi.ac.uk/files/sample.fasta")
        self.assertIn("dateModified", entity)

    # ------------------------------------------------------------------
    # Pre-built queryset
    # ------------------------------------------------------------------

    def test_sample_queryset_bypasses_filters(self):
        """Passing sample_queryset= ignores all sample filter kwargs."""
        self._make_sample(
            biosample="SAMEA001", ena_sample="ERS001", source_dataset="MFD"
        )
        self._make_sample(
            biosample="SAMEA002", ena_sample="ERS002", source_dataset="GTDB"
        )
        qs = Sample.objects.filter(source_dataset="GTDB")
        # source_dataset="MFD" filter is ignored because queryset is explicit
        crate = build_crate(sample_queryset=qs, source_dataset="MFD")
        self.assertIsNone(crate.get("#sample-SAMEA001"))
        self.assertIsNotNone(crate.get("#sample-SAMEA002"))

    def test_genome_queryset_bypasses_filters(self):
        """Passing genome_queryset= ignores all genome filter kwargs."""
        self._make_genome(accession="GCA_001", completeness=95.0)
        self._make_genome(accession="GCA_002", completeness=30.0)
        qs = Genome.objects.filter(accession="GCA_002")
        crate = build_crate(
            include_genomes=True, genome_queryset=qs, min_completeness=80.0
        )
        self.assertIsNone(crate.get("#genome-GCA_001"))
        self.assertIsNotNone(crate.get("#genome-GCA_002"))
