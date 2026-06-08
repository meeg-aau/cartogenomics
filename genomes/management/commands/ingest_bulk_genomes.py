from django.core.management.base import BaseCommand
from django.core.management import call_command


class Command(BaseCommand):
    help = "Bulk ingest genomes from a file with one accession per line"

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            "-f",
            required=True,
            help="File containing one accession per line (GCA or sample accessions)",
        )
        parser.add_argument(
            "--source",
            "-s",
            required=True,
            help='Source system, e.g. "MFD", "GTDB", "MGNIFY"',
        )
        parser.add_argument(
            "--version-label",
            "-vl",
            required=True,
            help='Version label, e.g. "mfd_genomes_2026_02_10"',
        )
        parser.add_argument(
            "--pipeline-version",
            "-pv",
            default="",
            help="Pipeline version string",
        )
        parser.add_argument(
            "--release-label",
            "-rl",
            default="1.0",
            help='Cartogenomics release label, default "1.0"',
        )
        parser.add_argument(
            "--continue-on-error",
            action="store_true",
            help="Continue processing remaining accessions if one fails",
            default=True,
        )

    def handle(self, *args, **options):
        file_path = options["file"]
        source = options["source"]
        version_label = options["version_label"]
        pipeline_version = options["pipeline_version"]
        release_label = options["release_label"]
        continue_on_error = options["continue_on_error"]

        with open(file_path) as f:
            accessions = [x.strip() for x in f if x.strip() and not x.startswith("#")]

        total = len(accessions)
        self.stdout.write(f"Processing {total} genome accessions")

        success = 0
        failed = 0

        for i, acc in enumerate(accessions, start=1):
            self.stdout.write(f"[{i}/{total}] {acc}")
            try:
                call_command(
                    "ingest_genome",
                    accession=acc,
                    source=source,
                    version_label=version_label,
                    pipeline_version=pipeline_version,
                    release_label=release_label,
                )
                success += 1
            except Exception as e:
                failed += 1
                self.stderr.write(self.style.ERROR(f"Failed for {acc}: {e}"))
                if not continue_on_error:
                    raise

        self.stdout.write(self.style.SUCCESS(f"Finished. Success: {success}, Failed: {failed}"))
