import logging
from pathlib import Path

from django.conf import settings
from django.contrib.gis.geos import Point
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from sample_metadata_curation.curate import curate_biosample

from api_fetch import parse_iso_date
from api_fetch.biosamples import BASE_URL, get_basic_sample_data
from api_fetch.ena import ENAClient
from external.models import ExternalResource
from runs.models import Run
from samples.models import Sample, SampleVersion
from versions.models import CartogenomicsRelease, IngestVersion

logger = logging.getLogger(__name__)
ena_api = ENAClient()


class Command(BaseCommand):
    help = "Fetch BioSample JSON, curate it, and add it into the Sample table."

    def add_arguments(self, parser):
        parser.add_argument(
            "--accession",
            "-a",
            type=str,
            required=True,
            help="Any INSDC style accession, e.g. SAME..., ERR..., ERX..., ERS...",
        )
        parser.add_argument(
            "--source",
            "-s",
            type=str,
            required=True,
            help='Source dataset label, e.g. "MFD"',
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
            help=(
                "Pipeline version used for curation or processing, "
                'e.g. "sample_metadata_curation 0.1.0"'
            ),
        )
        parser.add_argument(
            "--release-label",
            "-rl",
            type=str,
            default="1.0",
            help='Cartogenomics release label, default is "1.0"',
        )
        parser.add_argument(
            "--no-runs",
            action="store_true",
            help="Skip run ingestion (sample metadata only)",
        )

    @transaction.atomic
    def handle(self, *args, **opts):
        accession = opts["accession"]
        source_dataset = opts["source"]
        version_label = opts["version_label"]
        pipeline_version = opts["pipeline_version"]
        release_label = opts["release_label"]
        no_runs = opts["no_runs"]

        logger.info(f"Starting ingest for accession: {accession}")

        # Get related accessions from ENA
        try:
            runs_data = ena_api.get_all_run_accessions(accession)
        except Exception as e:
            raise CommandError(f"Failed to get accessions for {accession}: {e}")

        if not runs_data:
            raise CommandError(f"No data found for {accession}")

        biosample_acc = runs_data[0].get("biosample") if runs_data else None
        ena_sample_acc = runs_data[0].get("ena_sample") if runs_data else None
        logger.info(
            f"Resolved accessions: biosample={biosample_acc} "
            f"ena_sample={ena_sample_acc}"
        )

        fetch_acc = biosample_acc or ena_sample_acc
        if not fetch_acc:
            raise CommandError(
                f"Could not find a valid sample accession for {accession}"
            )

        logger.info(f"Fetching BioSample metadata for {fetch_acc}")
        try:
            raw = get_basic_sample_data(fetch_acc)
        except Exception as e:
            raise CommandError(f"Failed to fetch BioSample {fetch_acc}: {e}")

        if not raw:
            raise CommandError(f"No BioSample data returned for {fetch_acc}")

        # Set up IngestVersion
        release, _ = CartogenomicsRelease.objects.get_or_create(label=release_label)

        biosample_first_created = parse_iso_date(raw.get("submitted"))
        biosample_last_updated = parse_iso_date(raw.get("update"))

        version, version_created = IngestVersion.objects.update_or_create(
            source_system=IngestVersion.SourceSystem.BIOSAMPLES,
            label=version_label,
            data_type=IngestVersion.DataType.SAMPLE_METADATA,
            defaults={
                "pipeline_version": pipeline_version,
                "release": release,
            },
        )
        logger.debug(
            f"IngestVersion id={version.pk} label={version.label} "
            f"({'Created' if version_created else 'Using existing'})"
        )

        #   use whatever ingest_country_boundaries most recently downloaded,
        #   so sample curation and the CountryBoundary table are checked
        #   against the same Natural Earth release; fall back to whatever
        #   sample_metadata_curation has bundled if that hasn't run yet
        ne_zip_path = Path(settings.NATURAL_EARTH_ZIP_PATH)
        natural_earth_zip = ne_zip_path if ne_zip_path.exists() else None

        logger.info(f"Curating metadata for {fetch_acc}")
        try:
            #   use the MFD internally curated ontology
            if source_dataset == "MFD":
                curated = curate_biosample(
                    raw,
                    biome_keys=[
                        "01_mfd_sampletype",
                        "02_mfd_areatype",
                        "03_mfd_hab1",
                        "04_mfd_hab2",
                        "05_mfd_hab3",
                    ],
                    natural_earth_zip=natural_earth_zip,
                )
            else:
                curated = curate_biosample(raw, natural_earth_zip=natural_earth_zip)
        except Exception as e:
            raise CommandError(f"Failed to curate BioSample {fetch_acc}: {e}")

        lookup = {}
        if biosample_acc:
            lookup["biosample"] = biosample_acc
        elif ena_sample_acc:
            lookup["ena_sample"] = ena_sample_acc
        else:
            raise CommandError(
                f"Could not determine a lookup key for Sample from {accession}"
            )

        lat = curated.get("latitude")
        lon = curated.get("longitude")
        location = (
            Point(lon, lat, srid=4326) if lat is not None and lon is not None else None
        )

        #   reverse (polygon-derived) code is the geometric ground truth and matches
        #   CountryBoundary.iso_a2; only fall back to the reported code when there
        #   were no coordinates to reverse-geocode (e.g. ocean samples)
        inferred_country_code = curated.get("reverse_country_code") or curated.get(
            "reported_country_code"
        )

        curated_defaults = {
            "biosample": biosample_acc,
            "ena_sample": ena_sample_acc,
            "source_dataset": source_dataset,
            "latitude": lat,
            "longitude": lon,
            "location": location,
            "region": curated.get("region"),
            "locality": curated.get("locality"),
            "geography_check_status": curated.get("geo_check_status"),
            "geography_status_reason": curated.get("geo_check_reason"),
            "inferred_country_code": inferred_country_code,
            "coordinates_reversed": curated.get("coordinates_reversed"),
            "coord_precision_deg": curated.get("coord_precision_deg"),
            "ontology": curated.get("biome"),
            "raw_metadata": curated,
        }

        #   keep this separate so it does not influence the changed fields
        #   and version table
        sample_archive = {
            "archive_created": biosample_first_created,
            "archive_updated": biosample_last_updated,
        }

        #   check if the sample already exists with different fields
        changed_fields = []
        try:
            existing = Sample.objects.get(**lookup)
            changed_fields = [
                field
                for field, value in curated_defaults.items()
                if getattr(existing, field) != value
            ]
            if changed_fields:
                logger.info(
                    f"Sample {fetch_acc} already exists (id={existing.pk}) - "
                    f"{len(changed_fields)} field(s) changed"
                )
            else:
                logger.info(
                    f"Sample {fetch_acc} already exists (id={existing.pk}) "
                    "and no fields have changed."
                )
        except Sample.DoesNotExist:
            logger.info(f"Sample {fetch_acc} not found in DB - will be created.")

        try:
            sample, created = Sample.objects.update_or_create(
                **lookup,
                defaults={**curated_defaults, **sample_archive, "ingest": version},
            )
        except Exception as e:
            raise CommandError(f"Failed to create/update Sample for {accession}: {e}")

        logger.info(
            f"Sample id:{sample.pk} ({sample}) ({'Created' if created else 'Updated'})"
        )

        now = timezone.now()
        if created:
            SampleVersion.objects.create(
                sample=sample,
                ingest=version,
                valid_from=now,
                valid_to=None,
                **curated_defaults,
            )
        #   grab current valid version, set end date to now, open new
        #   version from now to keep provenance
        elif changed_fields:
            SampleVersion.objects.filter(sample=sample, valid_to__isnull=True).update(
                valid_to=now
            )
            SampleVersion.objects.create(
                sample=sample,
                ingest=version,
                valid_from=now,
                valid_to=None,
                **curated_defaults,
            )

        logger.info(f"ExternalResource for {sample.biosample}")
        try:
            ExternalResource.objects.update_or_create(
                source_system=ExternalResource.SourceSystem.BIOSAMPLES,
                accession=sample.biosample,
                ingest=version,
                defaults={
                    # is hardcoding the best way to do this?
                    "url": f"{BASE_URL}/{sample.biosample}.json",
                    "sample": sample,
                    "run": None,
                    "genome": None,
                    "first_created_external": biosample_first_created,
                    "last_modified_external": biosample_last_updated,
                },
            )
        except Exception as e:
            raise CommandError(
                f"Failed to create/update ExternalResource for {accession}: {e}"
            )

        logger.info(f"Ingest complete for {fetch_acc}")

        #   ingest runs if they exist and input requests runs
        if not no_runs and runs_data:
            run_ingest, _ = IngestVersion.objects.update_or_create(
                source_system=IngestVersion.SourceSystem.ENA,
                data_type=IngestVersion.DataType.READS,
                label=version_label,
                defaults={
                    "pipeline_version": pipeline_version,
                    "release": release,
                },
            )

            for run_item in runs_data:
                run_acc = run_item.get("run_accession")
                if not run_acc:
                    continue

                ena_first_created = parse_iso_date(run_item.get("first_created"))
                ena_last_updated = parse_iso_date(run_item.get("last_updated"))

                run_curated = {
                    "sample": sample,
                    "read_count": run_item.get("read_count"),
                    "sequencer": run_item.get("instrument_model")
                    or run_item.get("instrument_platform"),
                    "library_source": run_item.get("library_source"),
                    "library_strategy": run_item.get("library_strategy"),
                    "archive_created": ena_first_created,
                }

                run_obj, run_created = Run.objects.get_or_create(
                    accession=run_acc,
                    defaults={**run_curated, "ingest": run_ingest},
                )

                fastq_ftp = run_item.get("fastq_ftp") or ""
                for ftp_path in fastq_ftp.split(";"):
                    ftp_path = ftp_path.strip()
                    if not ftp_path:
                        continue
                    url = (
                        f"https://{ftp_path}"
                        if not ftp_path.startswith("http")
                        else ftp_path
                    )
                    filename = ftp_path.split("/")[-1]
                    ExternalResource.objects.update_or_create(
                        source_system=ExternalResource.SourceSystem.ENA,
                        accession=filename,
                        ingest=run_ingest,
                        defaults={
                            "url": url,
                            "run": run_obj,
                            "sample": None,
                            "genome": None,
                            "first_created_external": ena_first_created,
                            "last_modified_external": ena_last_updated,
                        },
                    )

                logger.info(
                    f"{'Created' if run_created else 'Skipped (already exists)'} "
                    f"Run {run_acc}"
                )

            logger.info(f"Ingested {len(runs_data)} run(s) for {fetch_acc}")

        self.stdout.write(
            self.style.SUCCESS(f"{'Created' if created else 'Updated'} Sample {sample}")
        )
