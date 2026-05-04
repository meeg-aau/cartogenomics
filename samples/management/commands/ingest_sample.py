import logging

from datetime import datetime
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from versions.models import IngestVersion, CartogenomicsRelease
from samples.models import Sample, SampleVersion
from runs.models import Run
from external.models import ExternalResource

from api_fetch.biosamples import get_basic_sample_data, BASE_URL
from api_fetch.ena import ENAClient
from sample_metadata_curation.curate import curate_biosample

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
            help="Accession, e.g. SAME..., ERR..., ERX..., ERS...",
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
            help='Pipeline version, e.g. "sample_metadata_curation 0.1.0"',
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
            biosample_acc = runs_data[0].get("biosample") if runs_data else None
            ena_sample_acc = runs_data[0].get("ena_sample") if runs_data else None
        except Exception as e:
            raise CommandError(f"Failed to get accessions for {accession}: {e}")

        logger.debug(f"Resolved accessions: biosample={biosample_acc} ena_sample={ena_sample_acc}")

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

        upstream_last_modified = None
        raw_update = raw.get("update")
        if raw_update:
            try:
                dt = datetime.fromisoformat(raw_update.replace("Z", "+00:00"))
                upstream_last_modified = dt if timezone.is_aware(dt) else timezone.make_aware(dt)
            except (ValueError, TypeError):
                logger.warning(f"Could not parse BioSamples 'update' date: {raw_update}")

        biosample_first_created = None
        raw_submitted = raw.get("submitted")
        if raw_submitted:
            try:
                dt = datetime.fromisoformat(raw_submitted.replace("Z", "+00:00"))
                biosample_first_created = dt if timezone.is_aware(dt) else timezone.make_aware(dt)
            except (ValueError, TypeError):
                logger.warning(f"Could not parse BioSamples 'submitted' date: {raw_submitted}")

        version, version_created = IngestVersion.objects.update_or_create(
            source_system=IngestVersion.SourceSystem.BIOSAMPLES,
            label=version_label,
            data_type=IngestVersion.DataType.SAMPLE_METADATA,
            defaults={
                "pipeline_version": pipeline_version,
                "release": release,
                "last_modified_internal": upstream_last_modified,
            }
        )
        logger.debug(f"IngestVersion id={version.pk} label={version.label} ({'Created' if version_created else 'Using existing'})")

        logger.info(f"Curating metadata for {fetch_acc}")
        try:
            curated = curate_biosample(
                raw,
                biome_keys=[
                    "01_mfd_sampletype",
                    "02_mfd_areatype",
                    "03_mfd_hab1",
                    "04_mfd_hab2",
                    "05_mfd_hab3",
                ],
            )
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

        curated_defaults = {
            "biosample": biosample_acc,
            "ena_sample": ena_sample_acc,
            "source_dataset": source_dataset,
            "latitude": curated.get("latitude"),
            "longitude": curated.get("longitude"),
            "region": curated.get("region"),
            "locality": curated.get("locality"),
            "geography_check_status": curated.get("geo_check_status"),
            "geography_status_reason": curated.get("geo_check_reason"),
            "ontology": curated.get("biome"),
            "raw_metadata": curated,
        }

        changed_fields = []
        try:
            existing = Sample.objects.get(**lookup)
            changed_fields = [
                field for field, value in curated_defaults.items()
                if getattr(existing, field) != value
            ]
            if changed_fields:
                logger.info(
                    f"Sample {fetch_acc} already exists (id={existing.pk}) - {len(changed_fields)} field(s) changed: {changed_fields}."
                )
            else:
                logger.info(
                    f"Sample {fetch_acc} already exists (id={existing.pk}) and no curated fields have changed."
                )
        except Sample.DoesNotExist:
            logger.info(f"Sample {fetch_acc} not found in DB - will be created.")

        try:
            sample, created = Sample.objects.update_or_create(
                **lookup,
                defaults={**curated_defaults, "ingest": version},
            )
        except Exception as e:
            raise CommandError(f"Failed to create/update Sample for {accession}: {e}")

        logger.info(f"Sample id={sample.pk} ({sample}) ({'Created' if created else 'Updated'})")

        now = timezone.now()
        if created:
            SampleVersion.objects.create(
                sample=sample,
                ingest=version,
                valid_from=now,
                valid_to=None,
                **curated_defaults,
            )
        elif changed_fields:
            SampleVersion.objects.filter(sample=sample, valid_to__isnull=True).update(valid_to=now)
            SampleVersion.objects.create(
                sample=sample,
                ingest=version,
                valid_from=now,
                valid_to=None,
                **curated_defaults,
            )

        logger.debug(f"ExternalResource for {sample.biosample}")
        try:
            ExternalResource.objects.update_or_create(
                source_system=ExternalResource.SourceSystem.BIOSAMPLES,
                accession=sample.biosample,
                ingest=version,
                defaults={
                    "url": f"{BASE_URL}/{sample.biosample}",
                    "sample": sample,
                    "run": None,
                    "genome": None,
                    "first_created_external": biosample_first_created,
                    "last_modified_external": upstream_last_modified,
                },
            )
        except Exception as e:
            raise CommandError(f"Failed to create/update ExternalResource for {accession}: {e}")

        logger.info(f"Ingest complete for {fetch_acc}")

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

            def _parse_date(raw):
                if not raw:
                    return None
                try:
                    dt = timezone.datetime.fromisoformat(raw.replace("Z", "+00:00"))
                    return dt if timezone.is_aware(dt) else timezone.make_aware(dt)
                except (ValueError, TypeError):
                    return None

            for run_item in runs_data:
                run_acc = run_item.get("run_accession")
                if not run_acc:
                    continue

                ena_first_created = _parse_date(run_item.get("first_created"))
                ena_last_updated = _parse_date(run_item.get("last_updated"))

                run_curated = {
                    "sample": sample,
                    "read_count": run_item.get("read_count"),
                    "sequencer": run_item.get("instrument_model") or run_item.get("instrument_platform"),
                    "library_source": run_item.get("library_source"),
                    "library_strategy": run_item.get("library_strategy"),
                }

                try:
                    existing_run = Run.objects.get(accession=run_acc)
                    changed = [f for f, v in run_curated.items() if getattr(existing_run, f) != v]
                    if changed:
                        logger.info(f"Run {run_acc} changed fields: {changed}.")
                    else:
                        logger.info(f"Run {run_acc} - no fields changed.")
                except Run.DoesNotExist:
                    logger.info(f"Run {run_acc} not found - will be created.")

                run_obj, run_created = Run.objects.update_or_create(
                    accession=run_acc,
                    defaults={**run_curated, "ingest": run_ingest},
                )

                ExternalResource.objects.update_or_create(
                    source_system=ExternalResource.SourceSystem.ENA,
                    accession=run_acc,
                    ingest=run_ingest,
                    defaults={
                        "url": f"https://www.ebi.ac.uk/ena/browser/view/{run_acc}",
                        "run": run_obj,
                        "sample": None,
                        "genome": None,
                        "first_created_external": ena_first_created,
                        "last_modified_external": ena_last_updated,
                    },
                )

                fastq_ftp = run_item.get("fastq_ftp") or ""
                for ftp_path in fastq_ftp.split(";"):
                    ftp_path = ftp_path.strip()
                    if not ftp_path:
                        continue
                    url = f"https://{ftp_path}" if not ftp_path.startswith("http") else ftp_path
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

                logger.info(f"{'Created' if run_created else 'Updated'} Run {run_acc}")

            logger.info(f"Ingested {len(runs_data)} run(s) for {fetch_acc}")

        self.stdout.write(
            self.style.SUCCESS(
                f"{'Created' if created else 'Updated'} Sample {sample}"
            )
        )
