from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Bulk ingest samples from a file with one accession per line"

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            "-f",
            required=True,
            help="File containing one accession per line",
        )
        parser.add_argument(
            "--source",
            "-s",
            required=True,
            help='Source dataset label, e.g. "MFD"',
        )
        parser.add_argument(
            "--no-runs",
            action="store_true",
            help="Skip run ingestion for each sample (sample metadata only)",
        )
        parser.add_argument(
            "--version-label",
            "-vl",
            required=True,
            help='Version label, e.g. "mfd_2026_01_15"',
        )
        parser.add_argument(
            "--pipeline-version",
            "-pv",
            default=None,
            help=(
                "Pipeline version used for curation or processing. "
                "Defaults to whatever SAMBAL version is currently installed."
            ),
        )
        parser.add_argument(
            "--release-label",
            "-rl",
            default="1.0",
            help='Cartogenomics release label, default is "1.0"',
        )
        parser.add_argument(
            "--continue-on-error",
            action="store_true",
            help="Continue processing even if one accession fails",
            default=True,
        )
        parser.add_argument(
            "--async",
            action="store_true",
            dest="run_async",
            help=(
                "Queue the batch as a Celery task and return immediately instead "
                "of running inline. Progress/results are tracked on the "
                "IngestJob row (see Django admin)."
            ),
        )

    def handle(self, *args, **options):
        file_path = options["file"]
        source = options["source"]
        no_runs = options["no_runs"]
        version_label = options["version_label"]
        pipeline_version = options["pipeline_version"]
        release_label = options["release_label"]
        continue_on_error = options["continue_on_error"]
        run_async = options["run_async"]

        with open(file_path) as f:
            accessions = [x.strip() for x in f if x.strip() and not x.startswith("#")]

        total = len(accessions)

        if run_async:
            from samples.tasks import ingest_bulk_samples_task
            from versions.models import IngestJob

            job = IngestJob.objects.create(
                kind=IngestJob.Kind.SAMPLES,
                total=total,
                params={
                    "accessions": accessions,
                    "source": source,
                    "version_label": version_label,
                    "pipeline_version": pipeline_version,
                    "release_label": release_label,
                    "no_runs": no_runs,
                },
            )
            ingest_bulk_samples_task.delay(job.id)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Queued IngestJob {job.id} ({total} accession(s)). "
                    "Check Django admin for progress/results."
                )
            )
            return

        self.stdout.write(f"Processing {total} accessions")

        success = 0
        failed = 0

        for i, acc in enumerate(accessions, start=1):
            self.stdout.write(f"[{i}/{total}] {acc}")

            try:
                call_command(
                    "ingest_sample",
                    accession=acc,
                    source=source,
                    version_label=version_label,
                    pipeline_version=pipeline_version,
                    release_label=release_label,
                    no_runs=no_runs,
                )
                success += 1
            except Exception as e:
                failed += 1
                self.stderr.write(self.style.ERROR(f"Failed for {acc}: {e}"))
                if not continue_on_error:
                    raise

        self.stdout.write(
            self.style.SUCCESS(f"Finished. Success: {success}, Failed: {failed}")
        )
