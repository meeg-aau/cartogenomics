"""
RO-Crate builder for Cartogenomics.

Entry point: build_crate()

Provenance model
----------------
Every entity in the crate is linked to its IngestVersion via wasGeneratedBy.
Each IngestVersion is represented as a CreateAction (the ingest event).
Each CreateAction references a SoftwareApplication (the pipeline that ran it).
The CartogenomicsRelease is a Dataset entity referenced from the root.
An export-time CreateAction is always added to record when and how this crate
was produced.

Entity graph per export
-----------------------
  ./                          Root dataset (filters, date, release reference)
  #export                     CreateAction — this export event
  #cartogenomics-db           SoftwareApplication — this DB
  #release-{label}            Dataset — the CartogenomicsRelease (if scoped)
  #ingest-{sys}-{type}-{lbl}  CreateAction — one per distinct IngestVersion
  #pipeline-{version}         SoftwareApplication — one per distinct pipeline
  #sample-{id}                ContextEntity — Sample + wasGeneratedBy → ingest
  #run-{accession}            ContextEntity — Run + wasGeneratedBy → ingest
  #genome-{accession}         ContextEntity — Genome + wasGeneratedBy → ingest
  {url}                       File — URL-only reference (fetch_remote=False)

Samples and Genomes are independent entities — Genome has no FK to Sample.
The link will come via the Parquet presence/absence matrix once implemented.

Usage
-----
    from rocrates.builder import build_crate

    crate = build_crate(source_dataset="MFD", release_label="1.0")
    crate = build_crate(include_genomes=True, genome_release_label="1.0",
                        min_completeness=90.0)

    import tempfile, zipfile, os
    with tempfile.TemporaryDirectory() as tmpdir:
        crate.write(tmpdir)
        with zipfile.ZipFile("export.zip", "w", zipfile.ZIP_DEFLATED) as zf:
            for root, _, files in os.walk(tmpdir):
                for f in files:
                    abs_path = os.path.join(root, f)
                    zf.write(abs_path, os.path.relpath(abs_path, tmpdir))
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from rocrate.rocrate import ROCrate
from rocrate.model.contextentity import ContextEntity


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_crate(
    *,
    label: str | None = None,

    # --- Sample selection ---
    sample_queryset=None,
    include_samples: bool = True,
    source_dataset: str | None = None,
    ontology: str | None = None,
    lat_min: float | None = None,
    lat_max: float | None = None,
    lon_min: float | None = None,
    lon_max: float | None = None,
    release_label: str | None = None,
    include_runs: bool = True,

    # --- Genome selection ---
    genome_queryset=None,
    include_genomes: bool = False,
    genome_release_label: str | None = None,
    min_completeness: float | None = None,
    max_contamination: float | None = None,
) -> ROCrate:
    """
    Build and return an ROCrate.

    All versioning information (ingest dates, pipelines, upstream versions,
    release metadata) is pulled from the DB and embedded as provenance
    entities in the crate graph.
    """
    from samples.models import Sample
    from genomes.models import Genome

    samples = []
    genomes = []

    if include_samples:
        if sample_queryset is None:
            sample_queryset = _apply_sample_filters(
                Sample.objects.all(),
                source_dataset=source_dataset,
                ontology=ontology,
                lat_min=lat_min, lat_max=lat_max,
                lon_min=lon_min, lon_max=lon_max,
                release_label=release_label,
            )
        sample_queryset = sample_queryset.select_related("ingest__release").prefetch_related(
            "external_resources",
            "runs__external_resources",
            "runs__ingest",
        )
        samples = list(sample_queryset)

    if include_genomes:
        if genome_queryset is None:
            genome_queryset = _apply_genome_filters(
                Genome.objects.all(),
                release_label=genome_release_label,
                min_completeness=min_completeness,
                max_contamination=max_contamination,
            )
        genome_queryset = genome_queryset.select_related("ingest__release").prefetch_related(
            "external_resources",
        )
        genomes = list(genome_queryset)

    crate = ROCrate()

    # Always present: the DB itself and the export action
    _add_cartogenomics_db_entity(crate)
    _add_export_action(crate, label=label, sample_count=len(samples), genome_count=len(genomes))

    _set_root_metadata(
        crate,
        label=label,
        source_dataset=source_dataset,
        ontology=ontology,
        lat_min=lat_min, lat_max=lat_max,
        lon_min=lon_min, lon_max=lon_max,
        release_label=release_label,
        genome_release_label=genome_release_label,
        sample_count=len(samples),
        genome_count=len(genomes),
    )

    for sample in samples:
        _ensure_ingest_entities(crate, sample.ingest)
        _add_sample(crate, sample)
        if include_runs:
            for run in sample.runs.all():
                _ensure_ingest_entities(crate, run.ingest)
                _add_run(crate, run, sample)

    for genome in genomes:
        _ensure_ingest_entities(crate, genome.ingest)
        _add_genome(crate, genome)

    return crate


# ---------------------------------------------------------------------------
# Filter helpers
# ---------------------------------------------------------------------------

def _apply_sample_filters(qs, *, source_dataset, ontology, lat_min, lat_max, lon_min, lon_max, release_label):
    if source_dataset:
        qs = qs.filter(source_dataset=source_dataset)
    if ontology:
        qs = qs.filter(ontology__icontains=ontology)
    if lat_min is not None:
        qs = qs.filter(latitude__gte=lat_min)
    if lat_max is not None:
        qs = qs.filter(latitude__lte=lat_max)
    if lon_min is not None:
        qs = qs.filter(longitude__gte=lon_min)
    if lon_max is not None:
        qs = qs.filter(longitude__lte=lon_max)
    if release_label:
        qs = qs.filter(ingest__release__label=release_label)
    return qs


def _apply_genome_filters(qs, *, release_label, min_completeness, max_contamination):
    if release_label:
        qs = qs.filter(ingest__release__label=release_label)
    if min_completeness is not None:
        qs = qs.filter(completeness__gte=min_completeness)
    if max_contamination is not None:
        qs = qs.filter(contamination__lte=max_contamination)
    return qs


# ---------------------------------------------------------------------------
# Root dataset + export action
# ---------------------------------------------------------------------------

def _set_root_metadata(
    crate, *, label, source_dataset, ontology,
    lat_min, lat_max, lon_min, lon_max,
    release_label, genome_release_label,
    sample_count, genome_count,
):
    parts = []
    if source_dataset:
        parts.append(source_dataset)
    if ontology:
        parts.append(ontology)
    if any(v is not None for v in [lat_min, lat_max, lon_min, lon_max]):
        parts.append(f"bbox({lat_min},{lat_max},{lon_min},{lon_max})")
    if release_label:
        parts.append(f"release:{release_label}")

    crate_label = label or (
        "Cartogenomics export — " + " | ".join(parts) if parts else "Cartogenomics export"
    )

    description_parts = []
    if sample_count:
        description_parts.append(f"{sample_count} samples")
    if genome_count:
        description_parts.append(f"{genome_count} genomes")

    crate.root_dataset["name"] = crate_label
    crate.root_dataset["datePublished"] = str(date.today())
    crate.root_dataset["description"] = (
        (", ".join(description_parts) + f" exported from Cartogenomics DB on {date.today()}.")
        if description_parts else f"Cartogenomics export — {date.today()}"
    )
    crate.root_dataset["keywords"] = [
        p for p in [source_dataset, ontology, release_label, genome_release_label] if p
    ]
    crate.root_dataset["wasGeneratedBy"] = {"@id": "#export"}

    if any(v is not None for v in [lat_min, lat_max, lon_min, lon_max]):
        crate.root_dataset["spatialCoverage"] = {
            "@id": "#spatial-coverage",
            "@type": "Place",
            "geo": {
                "@id": "#spatial-coverage-geo",
                "@type": "GeoShape",
                "box": f"{lat_min} {lon_min} {lat_max} {lon_max}",
            },
        }

    # Link to the release entity if it exists in the DB
    effective_release = release_label or genome_release_label
    if effective_release:
        _ensure_release_entity(crate, effective_release)
        crate.root_dataset["isPartOf"] = {"@id": f"#release-{effective_release}"}


def _add_cartogenomics_db_entity(crate: ROCrate) -> None:
    crate.add(ContextEntity(crate, "#cartogenomics-db", properties={
        "@type": "SoftwareApplication",
        "name": "Cartogenomics DB",
        "url": "https://github.com/meeg-aau/cartogenomics",
    }))


def _add_export_action(crate: ROCrate, *, label: str | None, sample_count: int, genome_count: int) -> None:
    description_parts = []
    if sample_count:
        description_parts.append(f"{sample_count} samples")
    if genome_count:
        description_parts.append(f"{genome_count} genomes")

    crate.add(ContextEntity(crate, "#export", properties={
        "@type": "CreateAction",
        "name": "Cartogenomics RO-Crate export",
        "description": ("Export of " + ", ".join(description_parts)) if description_parts else "Cartogenomics export",
        "endTime": _fmt_date(datetime.now(timezone.utc)),
        "instrument": {"@id": "#cartogenomics-db"},
        "result": {"@id": "./"},
    }))


# ---------------------------------------------------------------------------
# Provenance entities (IngestVersion, pipeline, release)
# ---------------------------------------------------------------------------

def _ingest_entity_id(ingest) -> str:
    slug = f"{ingest.source_system}-{ingest.data_type}-{ingest.label}".lower().replace(" ", "-")
    return f"#ingest-{slug}"


def _pipeline_entity_id(pipeline_version: str) -> str:
    return f"#pipeline-{pipeline_version.lower().replace(' ', '-')}"


def _ensure_ingest_entities(crate: ROCrate, ingest) -> None:
    """Add a CreateAction for the IngestVersion and its SoftwareApplication, if not already present."""
    ingest_id = _ingest_entity_id(ingest)
    if crate.get(ingest_id):
        return

    properties = {
        "@type": "CreateAction",
        "name": f"{ingest.source_system} {ingest.data_type.lower().replace('_', ' ')} ingest",
        "description": ingest.label,
        "object": {"@id": ingest.source_system},  # points at the source system entity
    }

    properties["endTime"] = _fmt_date(ingest.created_at)
    if ingest.last_modified_internal:
        properties["startTime"] = _fmt_date(ingest.last_modified_internal)
    if ingest.upstream_version:
        properties["version"] = ingest.upstream_version
    if ingest.notes:
        properties["description"] = f"{ingest.label} — {ingest.notes}"

    # Link to the pipeline that ran this ingest
    if ingest.pipeline_version:
        _ensure_pipeline_entity(crate, ingest.pipeline_version)
        properties["instrument"] = {"@id": _pipeline_entity_id(ingest.pipeline_version)}

    # Link to the release this ingest belongs to
    if ingest.release:
        _ensure_release_entity(crate, ingest.release.label, release_obj=ingest.release)
        properties["isPartOf"] = {"@id": f"#release-{ingest.release.label}"}

    crate.add(ContextEntity(crate, ingest_id, properties=properties))


def _ensure_pipeline_entity(crate: ROCrate, pipeline_version: str) -> None:
    pipeline_id = _pipeline_entity_id(pipeline_version)
    if crate.get(pipeline_id):
        return

    # Try to split "tool_name version_string" on the last space
    parts = pipeline_version.rsplit(" ", 1)
    name = parts[0] if len(parts) == 2 else pipeline_version
    version = parts[1] if len(parts) == 2 else None

    properties = {
        "@type": "SoftwareApplication",
        "name": name,
        "softwareVersion": version or pipeline_version,
    }
    crate.add(ContextEntity(crate, pipeline_id, properties=properties))


def _ensure_release_entity(crate: ROCrate, release_label: str, release_obj=None) -> None:
    release_id = f"#release-{release_label}"
    if crate.get(release_id):
        return

    properties = {
        "@type": "schema:Dataset",
        "name": release_label,
    }

    if release_obj is None:
        # Lazy-load from DB if only the label was given
        try:
            from versions.models import CartogenomicsRelease
            release_obj = CartogenomicsRelease.objects.get(label=release_label)
        except Exception:
            pass

    if release_obj:
        properties["dateCreated"] = _fmt_date(release_obj.created_at)
        if release_obj.notes:
            properties["description"] = release_obj.notes

    crate.add(ContextEntity(crate, release_id, properties=properties))


# ---------------------------------------------------------------------------
# Entity builders
# ---------------------------------------------------------------------------

def _add_sample(crate: ROCrate, sample) -> None:
    identifier = sample.biosample or sample.ena_sample or str(sample.pk)
    entity_id = f"#sample-{identifier}"

    properties = {
        "@type": ["schema:BioSample", "Thing"],
        "name": identifier,
        "identifier": [v for v in [sample.biosample, sample.ena_sample] if v],
        "dateCreated": _fmt_date(sample.created_at),
        "dateModified": _fmt_date(sample.updated_at),
        "wasGeneratedBy": {"@id": _ingest_entity_id(sample.ingest)},
    }
    if sample.source_dataset:
        properties["isPartOf"] = sample.source_dataset
    if sample.ontology:
        properties["environmentType"] = sample.ontology
    if sample.latitude is not None:
        properties["latitude"] = sample.latitude
    if sample.longitude is not None:
        properties["longitude"] = sample.longitude
    if sample.region:
        properties["addressRegion"] = sample.region
    if sample.locality:
        properties["addressLocality"] = sample.locality

    crate.add(ContextEntity(crate, entity_id, properties=properties))

    for ext in sample.external_resources.all():
        _add_external_file(crate, ext)


def _add_run(crate: ROCrate, run, sample) -> None:
    entity_id = f"#run-{run.accession}"
    sample_id = sample.biosample or sample.ena_sample or str(sample.pk)

    properties = {
        "@type": "schema:Dataset",
        "name": run.accession,
        "identifier": run.accession,
        "sample": {"@id": f"#sample-{sample_id}"},
        "dateCreated": _fmt_date(run.created_at),
        "wasGeneratedBy": {"@id": _ingest_entity_id(run.ingest)},
    }
    if run.sequencer:
        properties["instrument"] = run.sequencer
    if run.read_count is not None:
        properties["contentSize"] = run.read_count

    crate.add(ContextEntity(crate, entity_id, properties=properties))

    for ext in run.external_resources.all():
        _add_external_file(crate, ext)


def _add_genome(crate: ROCrate, genome) -> None:
    entity_id = f"#genome-{genome.accession}"

    properties = {
        "@type": ["schema:Dataset", "schema:Gene"],
        "name": genome.accession,
        "identifier": genome.accession,
        "dateCreated": _fmt_date(genome.created_at),
        "wasGeneratedBy": {"@id": _ingest_entity_id(genome.ingest)},
    }
    if genome.taxonomy:
        properties["taxonomicRange"] = genome.taxonomy
    if genome.completeness is not None:
        properties["completeness"] = genome.completeness
    if genome.contamination is not None:
        properties["contamination"] = genome.contamination
    if genome.completeness_software:
        properties["measurementTechnique"] = genome.completeness_software
    if genome.genome_size is not None:
        properties["contentSize"] = genome.genome_size
    if genome.n50 is not None:
        properties["n50"] = genome.n50

    crate.add(ContextEntity(crate, entity_id, properties=properties))

    for ext in genome.external_resources.all():
        _add_external_file(crate, ext)


def _add_external_file(crate: ROCrate, ext) -> None:
    if ext.url.lower().endswith(".parquet"):
        return

    media_type = _guess_media_type(ext.url)
    props = {
        "name": ext.url.split("/")[-1],
        "contentUrl": ext.url,
    }
    if media_type:
        props["encodingFormat"] = media_type
    if ext.source_system:
        props["publisher"] = ext.source_system
    if ext.first_created_external:
        props["dateCreated"] = _fmt_date(ext.first_created_external)
    if ext.last_modified_external:
        props["dateModified"] = _fmt_date(ext.last_modified_external)

    # fetch_remote=False — URL reference only, no file content downloaded
    crate.add_file(ext.url, fetch_remote=False, properties=props)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _fmt_date(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _guess_media_type(url: str) -> str | None:
    url_lower = url.lower()
    if url_lower.endswith((".fasta", ".fa", ".fna")):
        return "text/x-fasta"
    if url_lower.endswith((".fastq", ".fq")):
        return "text/x-fastq"
    if url_lower.endswith(".gz"):
        return "application/gzip"
    if url_lower.endswith(".tsv"):
        return "text/tab-separated-values"
    if url_lower.endswith(".csv"):
        return "text/csv"
    if url_lower.endswith(".json"):
        return "application/json"
    if url_lower.endswith(".bam"):
        return "application/x-bam"
    return None
