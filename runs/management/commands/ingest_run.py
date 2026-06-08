import logging

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from runs.models import Run
from samples.models import Sample
from versions.models import IngestVersion, CartogenomicsRelease
from external.models import ExternalResource

from api_fetch.ena import ENAClient

logger = logging.getLogger(__name__)
ena_api = ENAClient()


class Command(BaseCommand):
    help = "Fetch ENA run metadata and store it in the Run table."

    def add_arguments(self, parser):
        parser.add_argument(
            "--accession",
            "-a",
            type=str,
            required=True,
            help="Any ENA accession: run (ERR), experiment (ERX), or sample (ERS/SAME)",
        )
        parser.add_argument(
            "--version-label",
            "-vl",
            type=str,
            required=True,
            help='Version label, e.g. "mfd_2026_01_16"',
        )
        parser.add_argument(
            "--pipeline-version",
            "-pv",
            type=str,
            default="",
            help="Pipeline version string",
        )
        parser.add_argument(
            "--release-label",
            "-rl",
            type=str,
            default="1.0",
            help='Cartogenomics release label, default "1.0"',
        )

    @transaction.atomic
    def handle(self, *args, **opts):
        accession = opts["accession"]
        version_label = opts["version_label"]
        pipeline_version = opts["pipeline_version"]
        release_label = opts["release_label"]

        # Resolve all related accessions from ENA
        try:
            runs_data = ena_api.get_all_run_accessions(accession)
        except Exception as e:
            raise CommandError(f"Failed to resolve accessions for {accession}: {e}")

        if not runs_data:
            raise CommandError(f"Could not resolve a run accession from {accession}")

        run_item = runs_data[0]
        run_acc = run_item.get("run_accession")
        biosample_acc = run_item.get("biosample")
        ena_sample_acc = run_item.get("ena_sample")

        if not run_acc:
            raise CommandError(f"Could not resolve a run accession from {accession}")

        # Sample must already exist - ingest_sample should be run first
        lookup = {}
        if biosample_acc:
            lookup["biosample"] = biosample_acc
        elif ena_sample_acc:
            lookup["ena_sample"] = ena_sample_acc
        else:
            raise CommandError(f"No sample accession found for {accession}")

        try:
            sample = Sample.objects.get(**lookup)
        except Sample.DoesNotExist:
            raise CommandError(
                f"Sample not found for {lookup}. Run ingest_sample first."
            )

        run_data = run_item

        # Parse ENA date fields
        def parse_date(raw):
            if not raw:
                return None
            try:
                dt = timezone.datetime.fromisoformat(raw.replace("Z", "+00:00"))
                return dt if timezone.is_aware(dt) else timezone.make_aware(dt)
            except (ValueError, TypeError):
                return None

        ena_first_created = parse_date(run_data.get("first_created"))
        ena_last_updated = parse_date(run_data.get("last_updated"))

        # Set up IngestVersion
        release, _ = CartogenomicsRelease.objects.get_or_create(label=release_label)
        ingest, _ = IngestVersion.objects.update_or_create(
            source_system=IngestVersion.SourceSystem.ENA,
            data_type=IngestVersion.DataType.READS,
            label=version_label,
            defaults={
                "pipeline_version": pipeline_version,
                "release": release,
            },
        )

        # Build the curated field dict
        curated_defaults = {
            "sample": sample,
            "read_count": run_data.get("read_count"),
            "sequencer": run_data.get("instrument_model") or run_data.get("instrument_platform"),
            "library_source": run_data.get("library_source"),
            "library_strategy": run_data.get("library_strategy"),
        }

        try:
            existing = Run.objects.get(accession=run_acc)
            changed_fields = [
                field for field, value in curated_defaults.items()
                if getattr(existing, field) != value
            ]
            if changed_fields:
                logger.info(f"Run {run_acc} already exists (id={existing.pk}) - {len(changed_fields)} field(s) changed: {changed_fields}.")
            else:
                logger.info(f"Run {run_acc} already exists (id={existing.pk}) - no fields changed.")
        except Run.DoesNotExist:
            logger.info(f"Run {run_acc} not found in DB - will be created.")

        run, created = Run.objects.update_or_create(
            accession=run_acc,
            defaults={**curated_defaults, "ingest": ingest},
        )

        # ExternalResource - ENA browser link
        ExternalResource.objects.update_or_create(
            source_system=ExternalResource.SourceSystem.ENA,
            accession=run_acc,
            ingest=ingest,
            defaults={
                "url": f"https://www.ebi.ac.uk/ena/browser/view/{run_acc}",
                "run": run,
                "sample": None,
                "genome": None,
                "first_created_external": ena_first_created,
                "last_modified_external": ena_last_updated,
            },
        )

        # ExternalResource - one row per FASTQ file
        fastq_ftp = run_data.get("fastq_ftp") or ""
        for ftp_path in fastq_ftp.split(";"):
            ftp_path = ftp_path.strip()
            if not ftp_path:
                continue
            url = f"https://{ftp_path}" if not ftp_path.startswith("http") else ftp_path
            filename = ftp_path.split("/")[-1]
            ExternalResource.objects.update_or_create(
                source_system=ExternalResource.SourceSystem.ENA,
                accession=filename,
                ingest=ingest,
                defaults={
                    "url": url,
                    "run": run,
                    "sample": None,
                    "genome": None,
                    "first_created_external": ena_first_created,
                    "last_modified_external": ena_last_updated,
                },
            )

        self.stdout.write(self.style.SUCCESS(
            f"{'Created' if created else 'Updated'} Run {run_acc} linked to Sample {sample}"
        ))
