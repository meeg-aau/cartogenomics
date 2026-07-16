import os
import tempfile
import zipfile

from celery import shared_task


@shared_task
def build_rocrate_task(job_id):
    from rocrates.builder import build_crate
    from rocrates.models import ExportJob

    job = ExportJob.objects.get(id=job_id)
    job.status = ExportJob.Status.RUNNING
    job.save(update_fields=["status"])

    try:
        from rocrates.preview import generate_preview

        crate = build_crate(**job.params)
        output_path = f"/tmp/rocrate_{job_id}.zip"
        with tempfile.TemporaryDirectory() as tmpdir:
            crate.write(tmpdir)
            generate_preview(tmpdir)
            with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for root, _, files in os.walk(tmpdir):
                    for fname in files:
                        abs_path = os.path.join(root, fname)
                        zf.write(abs_path, os.path.relpath(abs_path, tmpdir))
        job.output_path = output_path
        job.status = ExportJob.Status.COMPLETE
    except Exception as e:
        job.status = ExportJob.Status.FAILED
        job.error = str(e)

    job.save(update_fields=["status", "output_path", "error"])
