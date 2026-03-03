from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from samples.models import Sample
from runs.models import Run
from versions.models import IngestVersion
from external.models import ExternalResource

from api_fetch.ena import get_run_from_sample  # <-- your existing function


class Command(BaseCommand):
    help = "Fetch ENA runs for a BioSample accession and store them in the Run table."

    def add_arguments(self, parser):
        parser.add_argument("--biosample", "-b", required=True, type=str, help="BioSample accession (SAMN/SAMEA...)")
        parser.add_argument("--ingest-label", "-l", required=True, type=str, help="Ingest label, e.g. mfd_2026_01_15_ena_runs")
        parser.add_argument("--release", "-r", default=None, type=str, help="Cartogenomics release label (optional)")

    @transaction.atomic
    def handle(self, *args, **opts):
        biosample = opts["biosample"]
        ingest_label = opts["ingest_label"]

        # 1) Find sample row
        try:
            sample = Sample.objects.get(biosample_accession=biosample)
        except Sample.DoesNotExist:
            raise CommandError(f"Sample not found for biosample_accession={biosample}. Ingest sample first.")

        # 2) Ensure ingest version exists
        ingest, _ = IngestVersion.objects.get_or_create(
            source_system="ENA",
            data_type="READS",
            label=ingest_label,
            defaults={"notes": "ENA runs ingested from portal API"},
        )

        # 3) Fetch runs from ENA portal
        run_data = get_run_from_sample(biosample)
        if not run_data:
            self.stdout.write(self.style.WARNING(f"No runs returned for {biosample}"))
            return

        created_count = 0
        updated_count = 0

        # run_data in your code is JSON list of dicts
        for r in run_data:
            run_acc = r.get("run_accession")
            if not run_acc:
                continue

            read_count = r.get("read_count") or r.get("reads") or None
            sequencer = r.get("instrument_platform") or r.get("instrument_model") or None

            obj, created = Run.objects.update_or_create(
                accession=run_acc,
                ingest=ingest,
                defaults={
                    "sample": sample,
                    "read_count": read_count,
                    "sequencer": sequencer,
                },
            )
            created_count += int(created)
            updated_count += int(not created)

            # 4) Optional: store external link
            ExternalResource.objects.update_or_create(
                source_system="ENA",
                resource_type="ENA_RUN",
                ingest=ingest,
                run=obj,
                defaults={
                    "uri": f"https://www.ebi.ac.uk/ena/browser/view/{run_acc}",
                    "external_id": run_acc,
                },
            )

        self.stdout.write(self.style.SUCCESS(
            f"Runs ingested for {biosample}: created={created_count} updated={updated_count}"
        ))