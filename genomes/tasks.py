from celery import shared_task


@shared_task
def ingest_bulk_genomes_task(job_id):
    from django.core.management import call_command
    from django.utils import timezone

    from versions.models import IngestJob

    job = IngestJob.objects.get(id=job_id)
    job.status = IngestJob.Status.RUNNING
    job.save(update_fields=["status"])

    params = job.params
    accessions = params["accessions"]
    job.total = len(accessions)
    job.save(update_fields=["total"])

    success = 0
    failed = 0
    errors = []
    for acc in accessions:
        try:
            call_command(
                "ingest_genome",
                accession=acc,
                source=params["source"],
                version_label=params["version_label"],
                pipeline_version=params.get("pipeline_version", ""),
                release_label=params.get("release_label", "1.0"),
            )
            success += 1
        except Exception as e:
            failed += 1
            errors.append({"accession": acc, "error": str(e)})

    job.success_count = success
    job.failed_count = failed
    job.errors = errors
    job.status = IngestJob.Status.COMPLETE
    job.finished_at = timezone.now()
    job.save(
        update_fields=[
            "success_count",
            "failed_count",
            "errors",
            "status",
            "finished_at",
        ]
    )
