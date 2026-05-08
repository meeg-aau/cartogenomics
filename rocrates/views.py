from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from rocrates.models import ExportJob
from rocrates.tasks import build_rocrate_task
from samples.models import Sample


def _parse_params(post):
    def _float(val):
        try:
            return float(val) if val else None
        except (ValueError, TypeError):
            return None

    return {
        "label": post.get("label") or None,
        "include_samples": bool(post.get("include_samples")),
        "source_dataset": post.get("source_dataset") or None,
        "ontology": post.get("ontology") or None,
        "lat_min": _float(post.get("lat_min")),
        "lat_max": _float(post.get("lat_max")),
        "lon_min": _float(post.get("lon_min")),
        "lon_max": _float(post.get("lon_max")),
        "release_label": post.get("release_label") or None,
        "include_runs": bool(post.get("include_runs")),
        "include_genomes": bool(post.get("include_genomes")),
        "genome_release_label": post.get("genome_release_label") or None,
        "min_completeness": _float(post.get("min_completeness")),
        "max_contamination": _float(post.get("max_contamination")),
    }


class ExportView(View):
    def get(self, request):
        return render(request, "rocrates/export.html", {
            "source_datasets": Sample.SourceDataset.choices,
        })

    def post(self, request):
        params = _parse_params(request.POST)
        job = ExportJob.objects.create(params=params)
        build_rocrate_task.delay(str(job.id))
        return redirect("rocrate_status", job_id=job.id)


class StatusView(View):
    def get(self, request, job_id):
        job = get_object_or_404(ExportJob, id=job_id)
        return render(request, "rocrates/status.html", {"job": job})


class DownloadView(View):
    def get(self, request, job_id):
        job = get_object_or_404(ExportJob, id=job_id)
        if job.status != ExportJob.Status.COMPLETE:
            raise Http404
        response = FileResponse(
            open(job.output_path, "rb"),
            as_attachment=True,
            filename=f"rocrate_{job_id}.zip",
        )
        return response
