"""
RO-Crate builder for Cartogenomics.

Entry point: build_crate() — convenience wrapper around CrateBuilder.

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
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timezone

import duckdb
from django.conf import settings
from rocrate.rocrate import ROCrate
from rocrate.model.contextentity import ContextEntity

from versions.models import CartogenomicsRelease
from samples.models import Sample
from genomes.models import Genome
from runs.models import Run

logger = logging.getLogger(__name__)

def build_crate(**kwargs) -> ROCrate:
    return CrateBuilder(**kwargs).build()


class CrateBuilder:

    def __init__(
        self,
        *,
        label: str | None = None,

        # --- Sample selection ---
        sample_queryset = None,
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
        genome_queryset = None,
        include_genomes: bool = False,
        genome_release_label: str | None = None,
        min_completeness: float | None = None,
        max_contamination: float | None = None,

        # --- Abundance cross-filter ---
        # Keep all filtered samples; include genomes detected in them.
        link_via_abundance: bool = False,
        min_abundance: float = 0.0,
    ):
        self.label = label
        self.sample_queryset = sample_queryset
        self.include_samples = include_samples
        self.source_dataset = source_dataset
        self.ontology = ontology
        self.lat_min = lat_min
        self.lat_max = lat_max
        self.lon_min = lon_min
        self.lon_max = lon_max
        self.release_label = release_label
        self.include_runs = include_runs
        self.genome_queryset = genome_queryset
        self.include_genomes = include_genomes
        self.genome_release_label = genome_release_label
        self.min_completeness = min_completeness
        self.max_contamination = max_contamination
        self.link_via_abundance = link_via_abundance
        self.min_abundance = min_abundance

        self.crate: ROCrate | None = None
        self.samples: list = []
        self.genomes: list = []

    def build(self) -> ROCrate:
        self._resolve_querysets() # query DB, populate samples and genomes
        self.crate = ROCrate() #    create an empty crate
        self._add_cartogenomics_db_entity()
        self._add_export_action() # set a timestamp for export
        self._set_root_metadata()
        #   loop to add sample and run
        for sample in self.samples:
            self._ensure_ingest_entities(sample.ingest)
            self._add_sample(sample)
            if self.include_runs:
                for run in sample.runs.all():
                    self._ensure_ingest_entities(run.ingest)
                    self._add_run(run, sample)
        #   loop to add genomes
        for genome in self.genomes:
            self._ensure_ingest_entities(genome.ingest)
            self._add_genome(genome)
        return self.crate

    #   query DB with filters
    def _resolve_querysets(self):
        if self.include_samples:
            if self.sample_queryset is None:
                self.sample_queryset = self._apply_sample_filters(Sample.objects.all())

        if self.include_genomes:
            if self.genome_queryset is None:
                self.genome_queryset = self._apply_genome_filters(Genome.objects.all())

        if self.link_via_abundance and self.include_samples and self.include_genomes:
            self.sample_queryset, self.genome_queryset = self._cross_filter_via_abundance()

        if self.include_samples:
            self.sample_queryset = self.sample_queryset.select_related("ingest__release").prefetch_related(
                "external_resources",
                "runs__external_resources",
                "runs__ingest",
            )
            self.samples = list(self.sample_queryset)

        if self.include_genomes:
            self.genome_queryset = self.genome_queryset.select_related("ingest__release").prefetch_related(
                "external_resources",
            )
            self.genomes = list(self.genome_queryset)

    def _apply_sample_filters(self, qs):
        if self.source_dataset:
            qs = qs.filter(source_dataset=self.source_dataset)
        if self.ontology:
            qs = qs.filter(ontology__icontains=self.ontology)
        if self.lat_min is not None:
            qs = qs.filter(latitude__gte=self.lat_min)
        if self.lat_max is not None:
            qs = qs.filter(latitude__lte=self.lat_max)
        if self.lon_min is not None:
            qs = qs.filter(longitude__gte=self.lon_min)
        if self.lon_max is not None:
            qs = qs.filter(longitude__lte=self.lon_max)
        if self.release_label:
            qs = qs.filter(ingest__release__label=self.release_label)
        return qs

    def _apply_genome_filters(self, qs):
        if self.genome_release_label:
            qs = qs.filter(ingest__release__label=self.genome_release_label)
        if self.min_completeness is not None:
            qs = qs.filter(completeness__gte=self.min_completeness)
        if self.max_contamination is not None:
            qs = qs.filter(contamination__lte=self.max_contamination)
        return qs

    def _cross_filter_via_abundance(self):
        abundance_file = getattr(settings, "ABUNDANCE_FILE", None)
        if not abundance_file or not os.path.exists(abundance_file):
            logger.warning("No abundance file found at %s; skipping cross-filtering", abundance_file)
            return self.sample_queryset, self.genome_queryset

        con = duckdb.connect()
        parquet_cols = {row[0] for row in con.execute(
            f"DESCRIBE SELECT * FROM read_parquet('{abundance_file}') LIMIT 0"
        ).fetchall()}

        run_accessions = list(
            Run.objects.filter(sample__in=self.sample_queryset).values_list("accession", flat=True)
        )
        matching_runs = [r for r in run_accessions if r in parquet_cols]
        if not matching_runs:
            con.close()
            logger.warning("No matching runs found in %s for %d samples", abundance_file, self.sample_queryset.count())
            return self.sample_queryset, self.genome_queryset.none()

        genome_accessions = list(self.genome_queryset.values_list("accession", flat=True))
        col_select = ", ".join(f'"{r}"' for r in matching_runs)
        genome_list = ", ".join(f"'{v}'" for v in genome_accessions)

        result = con.execute(f"""
            WITH long AS (
                UNPIVOT (
                    SELECT genome_id, {col_select}
                    FROM read_parquet('{abundance_file}')
                    WHERE genome_id IN ({genome_list})
                )
                ON COLUMNS(* EXCLUDE genome_id)
                INTO NAME run_id VALUE abundance
            )
            SELECT array_agg(DISTINCT genome_id)
            FROM long
            WHERE abundance > {self.min_abundance}
        """).fetchone()
        con.close()

        present_genomes = result[0] if result else []
        return self.sample_queryset, self.genome_queryset.filter(accession__in=present_genomes)

    # -----------------------------------------------------------------------
    # Root dataset + export action
    # -----------------------------------------------------------------------

    def _set_root_metadata(self):
        parts = []
        if self.source_dataset:
            parts.append(self.source_dataset)
        if self.ontology:
            parts.append(self.ontology)
        if any(v is not None for v in [self.lat_min, self.lat_max, self.lon_min, self.lon_max]):
            parts.append(f"bbox({self.lat_min},{self.lat_max},{self.lon_min},{self.lon_max})")
        if self.release_label:
            parts.append(f"release:{self.release_label}")

        crate_label = self.label or (
            "Cartogenomics export — " + " | ".join(parts) if parts else "Cartogenomics export"
        )

        description_parts = []
        if self.samples:
            description_parts.append(f"{len(self.samples)} samples")
        if self.genomes:
            description_parts.append(f"{len(self.genomes)} genomes")

        self.crate.root_dataset["name"] = crate_label
        self.crate.root_dataset["datePublished"] = str(date.today())
        self.crate.root_dataset["description"] = (
            (", ".join(description_parts) + f" exported from Cartogenomics DB on {date.today()}.")
            if description_parts else f"Cartogenomics export — {date.today()}"
        )
        self.crate.root_dataset["keywords"] = [
            p for p in [self.source_dataset, self.ontology, self.release_label, self.genome_release_label] if p
        ]
        self.crate.root_dataset["wasGeneratedBy"] = {"@id": "#export"}

        if any(v is not None for v in [self.lat_min, self.lat_max, self.lon_min, self.lon_max]):
            self.crate.root_dataset["spatialCoverage"] = {
                "@id": "#spatial-coverage",
                "@type": "Place",
                "geo": {
                    "@id": "#spatial-coverage-geo",
                    "@type": "GeoShape",
                    "box": f"{self.lat_min} {self.lon_min} {self.lat_max} {self.lon_max}",
                },
            }

        filters = {
            "@id": "#export-filters",
            "includeSamples": self.include_samples,
            "includeGenomes": self.include_genomes,
        }
        if self.include_samples:
            if self.source_dataset:        filters["sourceDataset"]  = self.source_dataset
            if self.ontology:              filters["ontology"]       = self.ontology
            if self.lat_min is not None:   filters["latMin"]         = self.lat_min
            if self.lat_max is not None:   filters["latMax"]         = self.lat_max
            if self.lon_min is not None:   filters["lonMin"]         = self.lon_min
            if self.lon_max is not None:   filters["lonMax"]         = self.lon_max
            if self.release_label:         filters["releaseLabel"]   = self.release_label
            filters["includeRuns"] = self.include_runs
        if self.include_genomes:
            if self.genome_release_label:          filters["genomeReleaseLabel"] = self.genome_release_label
            if self.min_completeness is not None:  filters["minCompleteness"]   = self.min_completeness
            if self.max_contamination is not None: filters["maxContamination"]  = self.max_contamination
        if self.link_via_abundance:
            filters["linkViaAbundance"] = True
            filters["minAbundance"]     = self.min_abundance
        self.crate.root_dataset["exportFilters"] = filters

        effective_release = self.release_label or self.genome_release_label
        if effective_release:
            self._ensure_release_entity(effective_release)
            self.crate.root_dataset["isPartOf"] = {"@id": f"#release-{effective_release}"}

    def _add_cartogenomics_db_entity(self):
        self.crate.add(ContextEntity(self.crate, "#cartogenomics-db", properties={
            "@type": "SoftwareApplication",
            "name": "Cartogenomics DB",
            "url": "https://github.com/meeg-aau/cartogenomics",
        }))

    def _add_export_action(self):
        description_parts = []
        if self.samples:
            description_parts.append(f"{len(self.samples)} samples")
        if self.genomes:
            description_parts.append(f"{len(self.genomes)} genomes")

        self.crate.add(ContextEntity(self.crate, "#export", properties={
            "@type": "CreateAction",
            "name": "Cartogenomics RO-Crate export",
            "description": ("Export of " + ", ".join(description_parts)) if description_parts else "Cartogenomics export",
            "endTime": _fmt_date(datetime.now(timezone.utc)),
            "instrument": {"@id": "#cartogenomics-db"},
            "result": {"@id": "./"},
        }))

    # -----------------------------------------------------------------------
    # Provenance entities
    # -----------------------------------------------------------------------

    @staticmethod
    def _ingest_entity_id(ingest) -> str:
        slug = f"{ingest.source_system}-{ingest.data_type}-{ingest.label}".lower().replace(" ", "-")
        return f"#ingest-{slug}"

    @staticmethod
    def _pipeline_entity_id(pipeline_version: str) -> str:
        return f"#pipeline-{pipeline_version.lower().replace(' ', '-')}"

    def _ensure_ingest_entities(self, ingest) -> None:
        ingest_id = self._ingest_entity_id(ingest)
        if self.crate.get(ingest_id):
            return

        properties = {"@type": "CreateAction",
                      "name": f"{ingest.source_system} {ingest.data_type.lower().replace('_', ' ')} ingest",
                      "description": ingest.label, "object": {"@id": ingest.source_system},
                      "endTime": _fmt_date(ingest.ingested_on)}

        if ingest.upstream_version:
            properties["version"] = ingest.upstream_version
        if ingest.notes:
            properties["description"] = f"{ingest.label} — {ingest.notes}"

        if ingest.pipeline_version:
            self._ensure_pipeline_entity(ingest.pipeline_version)
            properties["instrument"] = {"@id": self._pipeline_entity_id(ingest.pipeline_version)}

        if ingest.release:
            self._ensure_release_entity(ingest.release.label, release_obj=ingest.release)
            properties["isPartOf"] = {"@id": f"#release-{ingest.release.label}"}

        self.crate.add(ContextEntity(self.crate, ingest_id, properties=properties))

    def _ensure_pipeline_entity(self, pipeline_version: str) -> None:
        pipeline_id = self._pipeline_entity_id(pipeline_version)
        if self.crate.get(pipeline_id):
            return

        parts = pipeline_version.rsplit(" ", 1)
        name = parts[0] if len(parts) == 2 else pipeline_version
        version = parts[1] if len(parts) == 2 else None

        self.crate.add(ContextEntity(self.crate, pipeline_id, properties={
            "@type": "SoftwareApplication",
            "name": name,
            "softwareVersion": version or pipeline_version,
        }))

    def _ensure_release_entity(self, release_label: str, release_obj=None) -> None:
        release_id = f"#release-{release_label}"
        if self.crate.get(release_id):
            return

        properties = {
            "@type": "schema:Dataset",
            "name": release_label,
        }

        if release_obj is None:
            try:
                release_obj = CartogenomicsRelease.objects.get(label=release_label)
            except Exception:
                pass

        if release_obj:
            properties["dateCreated"] = _fmt_date(release_obj.created_at)
            if release_obj.notes:
                properties["description"] = release_obj.notes

        self.crate.add(ContextEntity(self.crate, release_id, properties=properties))

    # -----------------------------------------------------------------------
    # Entity builders
    # -----------------------------------------------------------------------

    def _add_sample(self, sample) -> None:
        identifier = sample.biosample or sample.ena_sample or str(sample.pk)
        entity_id = f"#sample-{identifier}"

        properties = {
            "@type": "schema:BioSample",
            "name": identifier,
            "identifier": [v for v in [sample.biosample, sample.ena_sample] if v],
            "dateCreated": _fmt_date(sample.created_at),
            "dateModified": _fmt_date(sample.updated_at),
            "wasGeneratedBy": {"@id": self._ingest_entity_id(sample.ingest)},
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

        self.crate.add(ContextEntity(self.crate, entity_id, properties=properties))

        for ext in sample.external_resources.all():
            self._add_external_file(ext)

    def _add_run(self, run, sample) -> None:
        entity_id = f"#run-{run.accession}"
        sample_id = sample.biosample or sample.ena_sample or str(sample.pk)

        properties = {
            "@type": "schema:Dataset",
            "name": run.accession,
            "identifier": run.accession,
            "sample": {"@id": f"#sample-{sample_id}"},
            "dateCreated": _fmt_date(run.created_at),
            "wasGeneratedBy": {"@id": self._ingest_entity_id(run.ingest)},
        }
        if run.sequencer:
            properties["instrument"] = run.sequencer
        if run.read_count is not None:
            properties["contentSize"] = run.read_count

        self.crate.add(ContextEntity(self.crate, entity_id, properties=properties))

        for ext in run.external_resources.all():
            self._add_external_file(ext)

    def _add_genome(self, genome) -> None:
        entity_id = f"#genome-{genome.accession}"

        properties = {
            "@type": ["schema:Dataset", "schema:Gene"],
            "name": genome.accession,
            "identifier": genome.accession,
            "dateCreated": _fmt_date(genome.created_at),
            "wasGeneratedBy": {"@id": self._ingest_entity_id(genome.ingest)},
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

        self.crate.add(ContextEntity(self.crate, entity_id, properties=properties))

        for ext in genome.external_resources.all():
            self._add_external_file(ext)

    def _add_external_file(self, ext) -> None:
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

        self.crate.add_file(ext.url, fetch_remote=False, properties=props)


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
