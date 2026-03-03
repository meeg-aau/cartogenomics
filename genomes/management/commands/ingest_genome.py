import csv

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from samples.models import Sample
from genomes.models import Genome
from versions.models import IngestVersion
from external.models import ExternalResource


class Command(BaseCommand):
    help = "Ingest genomes linked to samples from a TSV file."

    def add_arguments(self, parser):
        parser.add_argument("--tsv", "-t", required=True, type=str, help="Path to TSV file")
        parser.add_argument("--source-system", "-s", default="GTDB", type=str, help="GTDB/MGNIFY/MFD/etc")
        parser.add_argument("--ingest-label", "-l", required=True, type=str, help="Ingest label, e.g. gtdb_r220_genomes")

    @transaction.atomic
    def handle(self, *args, **opts):
        tsv_path = opts["tsv"]
        source_system = opts["source_system"]
        ingest_label = opts["ingest_label"]

        ingest, _ = IngestVersion.objects.get_or_create(
            source_system=source_system,
            data_type="GENOMES",
            label=ingest_label,
            defaults={"notes": f"Genomes ingested from TSV ({source_system})"},
        )

        created_count = 0
        updated_count = 0
        missing_samples = 0

        with open(tsv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            required = {"sample_biosample_accession", "genome_accession"}
            if not required.issubset(reader.fieldnames or set()):
                raise CommandError(f"TSV must contain columns: {sorted(required)}. Found: {reader.fieldnames}")

            for row in reader:
                biosample = row["sample_biosample_accession"].strip()
                genome_acc = row["genome_accession"].strip()

                try:
                    sample = Sample.objects.get(biosample_accession=biosample)
                except Sample.DoesNotExist:
                    missing_samples += 1
                    continue

                def to_float(x):
                    x = (x or "").strip()
                    return float(x) if x else None

                obj, created = Genome.objects.update_or_create(
                    accession=genome_acc,
                    ingest=ingest,
                    defaults={
                        "sample": sample,
                        "completeness": to_float(row.get("completeness")),
                        "contamination": to_float(row.get("contamination")),
                        "taxonomy": (row.get("taxonomy") or "").strip(),
                    },
                )
                created_count += int(created)
                updated_count += int(not created)

                # Optional: external link row
                ExternalResource.objects.update_or_create(
                    source_system=source_system,
                    resource_type="GENOME",
                    ingest=ingest,
                    genome=obj,
                    defaults={
                        "uri": row.get("url", "").strip() or "",
                        "external_id": genome_acc,
                    },
                )

        self.stdout.write(self.style.SUCCESS(
            f"Genomes ingested: created={created_count} updated={updated_count} missing_samples={missing_samples}"
        ))