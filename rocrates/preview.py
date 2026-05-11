"""
Generate a self-contained HTML preview from a written RO-Crate directory.

Usage:
    from rocrates.preview import generate_preview
    generate_preview("/path/to/crate/dir")   # writes ro-crate-preview.html
"""

from __future__ import annotations

import json
import os
from datetime import date


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def generate_preview(crate_dir: str) -> None:
    meta_path = os.path.join(crate_dir, "ro-crate-metadata.json")
    with open(meta_path, encoding="utf-8") as f:
        metadata = json.load(f)

    graph = {e["@id"]: e for e in metadata.get("@graph", [])}
    root = graph.get("./", {})

    entities = list(graph.values())
    samples   = [e for e in entities if _has_type(e, "BioSample")]
    runs      = [e for e in entities if _has_type(e, "Dataset") and e["@id"].startswith("#run-")]
    genomes   = [e for e in entities if e["@id"].startswith("#genome-")]
    files     = [e for e in entities if _is_file(e)]
    actions   = [e for e in entities if _has_type(e, "CreateAction")]
    pipelines = [e for e in entities if _has_type(e, "SoftwareApplication")]
    releases  = [e for e in entities if _has_type(e, "schema:Dataset") or (
                  _has_type(e, "Dataset") and e["@id"].startswith("#release-"))]

    try:
        from django.conf import settings
        abundance_file = getattr(settings, "ABUNDANCE_FILE", None)
    except Exception:
        abundance_file = None

    html = _render(root, graph, samples, runs, genomes, files, actions, pipelines, releases, metadata, abundance_file)

    out_path = os.path.join(crate_dir, "ro-crate-preview.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _has_type(entity: dict, type_str: str) -> bool:
    t = entity.get("@type", [])
    if isinstance(t, str):
        t = [t]
    return any(type_str in v for v in t)


def _is_file(entity: dict) -> bool:
    t = entity.get("@type", [])
    if isinstance(t, str):
        t = [t]
    return "File" in t and entity.get("@id", "").startswith("http")


def _pill(entity_id: str) -> str:
    if entity_id.startswith("#sample-"):   return "pill-sample",  "Sample"
    if entity_id.startswith("#run-"):      return "pill-run",     "Run"
    if entity_id.startswith("#genome-"):   return "pill-genome",  "Genome"
    if entity_id.startswith("#release-"):  return "pill-release", "Release"
    if entity_id.startswith("#ingest-"):   return "pill-action",  "Ingest"
    if entity_id.startswith("#pipeline-"): return "pill-software","Pipeline"
    if entity_id.startswith("#export"):    return "pill-action",  "Export"
    if entity_id == "./":                  return "pill-root",    "Root"
    if entity_id.startswith("http"):       return "pill-file",    "File"
    return "pill-root", "Entity"


def _fmt_val(v, graph: dict) -> str:
    if v is None:
        return '<span style="color:var(--muted)">null</span>'
    if isinstance(v, bool):
        return f'<span style="color:var(--purple)">{str(v).lower()}</span>'
    if isinstance(v, (int, float)):
        return f'<span style="color:var(--amber)">{v}</span>'
    if isinstance(v, dict) and "@id" in v:
        ref_id = v["@id"]
        css, label = _pill(ref_id)
        return f'<span class="link-ref {css}">→ {_esc(ref_id)}</span>'
    if isinstance(v, list):
        parts = [_fmt_val(i, graph) for i in v]
        return ", ".join(parts)
    return f'<code>{_esc(str(v))}</code>'


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _prop_table(entity: dict, graph: dict, skip: set | None = None) -> str:
    skip = (skip or set()) | {"@id", "@type"}
    rows = []
    for k, v in entity.items():
        if k in skip:
            continue
        rows.append(
            f'<tr><td>{_esc(k)}</td><td>{_fmt_val(v, graph)}</td></tr>'
        )
    if not rows:
        return '<p style="color:var(--muted);font-size:12px;padding:8px 0">No properties.</p>'
    return f'<table class="prop-table">{"".join(rows)}</table>'


def _entity_card(entity: dict, graph: dict, extra_header: str = "") -> str:
    eid = entity.get("@id", "?")
    css, label = _pill(eid)
    types = entity.get("@type", [])
    if isinstance(types, str):
        types = [types]
    type_label = " / ".join(t.replace("schema:", "") for t in types) if types else label

    return f"""
<div class="entity-card">
  <div class="entity-card-header" onclick="this.parentElement.classList.toggle('open')">
    <span class="entity-type-pill {css}">{type_label}</span>
    <span class="entity-id">{_esc(eid)}</span>
    {extra_header}
    <span class="chevron">▶</span>
  </div>
  <div class="entity-card-body">
    {_prop_table(entity, graph)}
  </div>
</div>"""


# ---------------------------------------------------------------------------
# Section renderers
# ---------------------------------------------------------------------------

def _sec_overview(root: dict, samples, runs, genomes, files, actions, pipelines, releases) -> str:
    name = root.get("name", "Cartogenomics Export")
    desc = root.get("description", "")
    pub  = root.get("datePublished", str(date.today()))
    release_ids = [r["@id"].replace("#release-", "") for r in releases if r["@id"].startswith("#release-")]
    release_str = ", ".join(release_ids) if release_ids else "—"

    cards = [
        ("Samples",   len(samples),   "c-green",  "🧪"),
        ("Runs",      len(runs),      "c-blue",   "🔬"),
        ("Genomes",   len(genomes),   "c-purple", "🧬"),
        ("Files",     len(files),     "c-teal",   "📂"),
        ("Ingests",   len([a for a in actions if a["@id"] != "#export"]), "c-amber", "⚙️"),
    ]
    stat_html = "".join(f"""
      <div class="stat-card">
        <div class="label">{icon} {label}</div>
        <div class="value {cls}">{count}</div>
      </div>""" for label, count, cls, icon in cards)

    return f"""
<div class="section-heading">
  <h2>{_esc(name)}</h2>
  <p>{_esc(desc)}</p>
</div>
<div style="color:var(--muted);font-size:13px;margin-bottom:20px">
  📅 Published {pub} &nbsp;·&nbsp; 🔖 Release: <code>{release_str}</code>
</div>
<div class="summary-grid">{stat_html}</div>
{_filter_summary(root)}"""


def _filter_summary(root: dict) -> str:
    f = root.get("exportFilters")
    if not f:
        return ""

    def row(label, value):
        return f'<tr><td class="fs-label">{_esc(label)}</td><td class="fs-value">{_esc(str(value))}</td></tr>'

    def badge(text, cls=""):
        return f'<span class="fs-badge {cls}">{_esc(text)}</span>'

    sections = []

    # Sample filters
    if f.get("includeSamples"):
        rows = []
        if f.get("sourceDataset"):   rows.append(row("Source dataset", f["sourceDataset"]))
        if f.get("releaseLabel"):     rows.append(row("Release", f["releaseLabel"]))
        if f.get("ontology"):         rows.append(row("Biome / ontology", f["ontology"]))
        has_bbox = any(k in f for k in ("latMin", "latMax", "lonMin", "lonMax"))
        if has_bbox:
            bbox = (
                f'lat {f.get("latMin", "—")} → {f.get("latMax", "—")}, '
                f'lon {f.get("lonMin", "—")} → {f.get("lonMax", "—")}'
            )
            rows.append(row("Bounding box", bbox))
        runs_str = "included" if f.get("includeRuns", True) else "excluded"
        rows.append(row("Sequencing runs", runs_str))
        if not any(f.get(k) for k in ("sourceDataset", "releaseLabel", "ontology")) and not has_bbox:
            rows.insert(0, f'<tr><td colspan="2" class="fs-none">No sample filters — all samples included</td></tr>')
        table = f'<table class="fs-table">{"".join(rows)}</table>'
        sections.append(f'<div class="fs-section"><div class="fs-heading">{badge("Samples", "badge-sample")} Filters</div>{table}</div>')

    # Genome filters
    if f.get("includeGenomes"):
        rows = []
        if f.get("genomeReleaseLabel"):  rows.append(row("Release", f["genomeReleaseLabel"]))
        if f.get("minCompleteness") is not None: rows.append(row("Min completeness", f'{f["minCompleteness"]}%'))
        if f.get("maxContamination") is not None: rows.append(row("Max contamination", f'{f["maxContamination"]}%'))
        if not rows:
            rows.append(f'<tr><td colspan="2" class="fs-none">No genome filters — all genomes included</td></tr>')
        table = f'<table class="fs-table">{"".join(rows)}</table>'
        sections.append(f'<div class="fs-section"><div class="fs-heading">{badge("Genomes", "badge-genome")} Filters</div>{table}</div>')

    # Abundance
    if f.get("linkViaAbundance"):
        direction = f.get("abundanceDirection", "samples_to_genomes")
        dir_label = "Samples → Genomes" if direction == "samples_to_genomes" else "Genomes → Samples"
        threshold = f.get("minAbundance", 0.0)
        threshold_str = str(threshold) if threshold else "0.0 (any detection)"
        rows = [row("Direction", dir_label), row("Min abundance", threshold_str)]
        table = f'<table class="fs-table">{"".join(rows)}</table>'
        sections.append(f'<div class="fs-section"><div class="fs-heading">{badge("Abundance", "badge-abundance")} Cross-filter</div>{table}</div>')

    if not sections:
        return ""

    inner = "".join(sections)
    return f'<div class="filter-summary">{inner}</div>'


def _sec_entities(entities: list, graph: dict) -> str:
    if not entities:
        return '<p style="color:var(--muted)">None in this export.</p>'
    return "".join(_entity_card(e, graph) for e in entities)


def _sec_provenance(actions: list, pipelines: list, releases: list, graph: dict) -> str:
    html = ""
    if releases:
        html += '<h3 style="font-size:13px;color:var(--muted);margin-bottom:12px">Releases</h3>'
        html += "".join(_entity_card(e, graph) for e in releases)
    if actions:
        html += '<h3 style="font-size:13px;color:var(--muted);margin:20px 0 12px">Ingest actions</h3>'
        html += "".join(_entity_card(e, graph) for e in actions)
    if pipelines:
        html += '<h3 style="font-size:13px;color:var(--muted);margin:20px 0 12px">Pipelines</h3>'
        html += "".join(_entity_card(e, graph) for e in pipelines)
    return html or '<p style="color:var(--muted)">No provenance entities.</p>'


def _sec_abundance(genomes: list, runs: list, samples: list, abundance_file) -> str:
    if not genomes or not runs:
        return '<p style="color:var(--muted)">Abundance view requires both genomes and runs in this export.</p>'
    if not abundance_file or not os.path.exists(abundance_file):
        return '<p style="color:var(--muted)">Abundance Parquet file not configured or not found on this system.</p>'

    try:
        import duckdb
    except ImportError:
        return '<p style="color:var(--muted)">DuckDB not installed — cannot read abundance data.</p>'

    genome_accessions = [g["@id"].replace("#genome-", "") for g in genomes]
    genome_taxonomy   = {g["@id"].replace("#genome-", ""): g.get("taxonomicRange", "") for g in genomes}

    run_accessions = [r["@id"].replace("#run-", "") for r in runs]
    run_to_sample  = {}
    for r in runs:
        acc = r["@id"].replace("#run-", "")
        ref = r.get("sample", {})
        if isinstance(ref, dict):
            run_to_sample[acc] = ref.get("@id", "").replace("#sample-", "")

    sample_meta = {}
    for s in samples:
        bs = s.get("name", "")
        sample_meta[bs] = {
            "region":   s.get("addressRegion", ""),
            "locality": s.get("addressLocality", ""),
            "lat": s.get("latitude"),
            "lon": s.get("longitude"),
        }

    con = duckdb.connect()
    try:
        parquet_cols = {row[0] for row in con.execute(
            f"DESCRIBE SELECT * FROM read_parquet('{abundance_file}') LIMIT 0"
        ).fetchall()}
        matching_runs    = [r for r in run_accessions    if r in parquet_cols]
        matching_genomes = [g for g in genome_accessions if True]

        if not matching_runs:
            return '<p style="color:var(--muted)">No run accessions in this export matched the abundance Parquet columns.</p>'

        col_select  = ", ".join(f'"{r}"' for r in matching_runs)
        genome_list = ", ".join(f"'{g}'" for g in matching_genomes)

        rows = con.execute(f"""
            WITH long AS (
                UNPIVOT (
                    SELECT genome_id, {col_select}
                    FROM read_parquet('{abundance_file}')
                    WHERE genome_id IN ({genome_list})
                )
                ON COLUMNS(* EXCLUDE genome_id)
                INTO NAME run_id VALUE abundance
            )
            SELECT genome_id, run_id, abundance
            FROM long
            WHERE abundance > 0
        """).fetchall()
    finally:
        con.close()

    # Aggregate per sample: max abundance across runs for each genome
    sample_abund = {}  # {sample_bs: {genome_acc: max_pct}}
    for genome_id, run_id, abund in rows:
        bs = run_to_sample.get(run_id, run_id)
        sample_abund.setdefault(bs, {})
        pct = round(float(abund) * 100, 1)
        if pct > sample_abund[bs].get(genome_id, 0):
            sample_abund[bs][genome_id] = pct

    js_samples = json.dumps([
        {
            "id":       bs,
            "region":   sample_meta.get(bs, {}).get("region", ""),
            "locality": sample_meta.get(bs, {}).get("locality", ""),
            "lat":      sample_meta.get(bs, {}).get("lat"),
            "lon":      sample_meta.get(bs, {}).get("lon"),
            "abund":    sample_abund.get(bs, {}),
        }
        for bs in sample_meta
    ])
    js_genomes = json.dumps([
        {"id": acc, "taxonomy": genome_taxonomy.get(acc, "")}
        for acc in genome_accessions
    ])

    genome_headers = "".join(
        f'<th style="padding:6px 10px;border-bottom:1px solid var(--border);color:var(--purple);'
        f'text-align:center;white-space:nowrap;font-size:11px;writing-mode:vertical-rl;'
        f'transform:rotate(180deg);max-height:120px;" title="{_esc(genome_taxonomy.get(acc,""))}">'
        f'{_esc(acc)}</th>'
        for acc in genome_accessions
    )

    return f"""
<div style="display:flex;gap:12px;margin-bottom:24px;align-items:center;flex-wrap:wrap;">
  <label style="font-size:12px;color:var(--muted);">Min abundance</label>
  <input id="abund-thresh" type="range" min="0" max="100" value="0"
    oninput="filterAbundance(); document.getElementById('abund-val').textContent=this.value+'%'"
    style="width:160px;accent-color:var(--accent);" />
  <span id="abund-val" style="font-size:13px;font-family:monospace;color:var(--accent);">0%</span>
  <span id="match-count" style="font-size:12px;color:var(--muted);margin-left:8px;"></span>
</div>
<div style="overflow-x:auto;">
  <table id="matrix-table" style="border-collapse:collapse;font-size:12px;">
    <thead>
      <tr>
        <th style="text-align:left;padding:8px 12px;border-bottom:1px solid var(--border);color:var(--muted);font-weight:600;white-space:nowrap;">Sample</th>
        <th style="text-align:left;padding:8px 12px;border-bottom:1px solid var(--border);color:var(--muted);white-space:nowrap;">Location</th>
        {genome_headers}
      </tr>
    </thead>
    <tbody id="matrix-body"></tbody>
  </table>
</div>
<script>
const _samples = {js_samples};
const _genomes = {js_genomes};
function abundColor(v) {{
  if (!v) return 'rgba(136,145,168,.15)';
  if (v >= 80) return 'rgba(61,214,140,.7)';
  if (v >= 50) return 'rgba(245,166,35,.6)';
  return 'rgba(240,101,101,.45)';
}}
function filterAbundance() {{
  const thresh = parseFloat(document.getElementById('abund-thresh').value);
  let html = '', matches = 0;
  for (const s of _samples) {{
    const maxV = Math.max(0, ..._genomes.map(g => s.abund[g.id] || 0));
    const pass = maxV >= thresh;
    if (pass && thresh > 0) matches++;
    const loc = [s.locality, s.region].filter(Boolean).join(', ') || '—';
    const cells = _genomes.map(g => {{
      const v = s.abund[g.id] || 0;
      const bg = abundColor(v);
      const label = v ? v.toFixed(1)+'%' : '';
      return `<td style="text-align:center;padding:4px 6px;border-bottom:1px solid var(--border);">
        <span style="display:inline-block;min-width:36px;padding:2px 4px;border-radius:4px;
          background:${{bg}};font-family:monospace;font-size:11px;color:var(--text);">${{label}}</span>
      </td>`;
    }}).join('');
    html += `<tr style="opacity:${{pass||thresh===0?1:0.25}};transition:opacity .2s;">
      <td style="padding:6px 12px;border-bottom:1px solid var(--border);font-family:monospace;font-size:11px;color:var(--green);white-space:nowrap;">${{s.id}}</td>
      <td style="padding:6px 12px;border-bottom:1px solid var(--border);color:var(--muted);white-space:nowrap;font-size:11px;">${{loc}}</td>
      ${{cells}}
    </tr>`;
  }}
  document.getElementById('matrix-body').innerHTML = html;
  document.getElementById('match-count').textContent =
    thresh > 0 ? `${{matches}} of ${{_samples.length}} samples with any genome ≥ ${{thresh}}%` : `${{_samples.length}} samples`;
}}
window.addEventListener('DOMContentLoaded', () => filterAbundance());
</script>"""


def _sec_jsonld(metadata: dict) -> str:
    raw = json.dumps(metadata, indent=2, ensure_ascii=False)
    return f"""
<div class="tab-row">
  <button class="tab-btn active" onclick="showTab('tab-raw', this)">Raw JSON-LD</button>
</div>
<div id="tab-raw" class="tab-panel active">
  <div class="json-block">{_esc(raw)}</div>
</div>"""


# ---------------------------------------------------------------------------
# Full HTML renderer
# ---------------------------------------------------------------------------

def _render(root, graph, samples, runs, genomes, files, actions, pipelines, releases, metadata, abundance_file=None) -> str:
    name = root.get("name", "Cartogenomics Export")
    pub  = root.get("datePublished", str(date.today()))
    release_ids = [r["@id"].replace("#release-", "") for r in releases if r["@id"].startswith("#release-")]
    release_str = ", ".join(release_ids) if release_ids else "—"

    summary_parts = []
    if samples:  summary_parts.append(f"{len(samples)} samples")
    if runs:     summary_parts.append(f"{len(runs)} runs")
    if genomes:  summary_parts.append(f"{len(genomes)} genomes")
    if files:    summary_parts.append(f"{len(files)} files")
    summary_str = " · ".join(summary_parts) or "empty crate"

    export_action = graph.get("#export", {})
    export_time = export_action.get("endTime", pub)

    CSS = _css()

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{_esc(name)}</title>
  <style>{CSS}</style>
</head>
<body>

<header>
  <div class="badge">RO-Crate · Cartogenomics</div>
  <h1>{_esc(name)}</h1>
  <div class="meta">
    <span><span class="dot"></span> {summary_str}</span>
    <span>📅 Exported {export_time[:10] if export_time else pub}</span>
    <span>🔖 Release: <code>{release_str}</code></span>
  </div>
</header>

<div class="layout">
  <nav class="sidebar">
    <h3>Contents</h3>
    <a class="nav-item active" onclick="showSection('overview', this)">
      <span class="icon">🏠</span> Overview
    </a>
    <a class="nav-item" onclick="showSection('samples', this)">
      <span class="icon">🧪</span> Samples <span class="nav-count">{len(samples)}</span>
    </a>
    <a class="nav-item" onclick="showSection('runs', this)">
      <span class="icon">🔬</span> Runs <span class="nav-count">{len(runs)}</span>
    </a>
    <a class="nav-item" onclick="showSection('genomes', this)">
      <span class="icon">🧬</span> Genomes <span class="nav-count">{len(genomes)}</span>
    </a>
    <a class="nav-item" onclick="showSection('files', this)">
      <span class="icon">📂</span> External Files <span class="nav-count">{len(files)}</span>
    </a>
    <hr class="nav-sep" />
    <h3>Provenance</h3>
    <a class="nav-item" onclick="showSection('provenance', this)">
      <span class="icon">⚙️</span> Ingest &amp; Pipeline
    </a>
    <hr class="nav-sep" />
    <h3>Data</h3>
    <a class="nav-item" onclick="showSection('abundance', this)">
      <span class="icon">📊</span> Abundance <span class="nav-count">{len(genomes)}×{len(samples)}</span>
    </a>
    <hr class="nav-sep" />
    <h3>Raw</h3>
    <a class="nav-item" onclick="showSection('jsonld', this)">
      <span class="icon">{{ }}</span> JSON-LD
    </a>
  </nav>

  <main>
    <section id="sec-overview" class="active">
      {_sec_overview(root, samples, runs, genomes, files, actions, pipelines, releases)}
    </section>
    <section id="sec-samples">
      <div class="section-heading"><h2>Samples</h2><p>{len(samples)} BioSamples in this export</p></div>
      {_sec_entities(samples, graph)}
    </section>
    <section id="sec-runs">
      <div class="section-heading"><h2>Runs</h2><p>{len(runs)} sequencing runs</p></div>
      {_sec_entities(runs, graph)}
    </section>
    <section id="sec-genomes">
      <div class="section-heading"><h2>Genomes</h2><p>{len(genomes)} MAGs</p></div>
      {_sec_entities(genomes, graph)}
    </section>
    <section id="sec-files">
      <div class="section-heading"><h2>External Files</h2><p>URL references — not downloaded into crate</p></div>
      {_sec_entities(files, graph)}
    </section>
    <section id="sec-provenance">
      <div class="section-heading"><h2>Provenance</h2><p>Ingest actions, pipelines, and releases</p></div>
      {_sec_provenance(actions, pipelines, releases, graph)}
    </section>
    <section id="sec-abundance">
      <div class="section-heading"><h2>Genome × Sample Abundance</h2><p>Abundance values from Parquet — aggregated per sample as max across runs. Select a genome and drag the threshold slider to filter rows.</p></div>
      {_sec_abundance(genomes, runs, samples, abundance_file)}
    </section>
    <section id="sec-jsonld">
      <div class="section-heading"><h2>JSON-LD</h2><p>Raw ro-crate-metadata.json</p></div>
      {_sec_jsonld(metadata)}
    </section>
  </main>
</div>

<script>
function showSection(id, el) {{
  document.querySelectorAll('section').forEach(s => s.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  document.getElementById('sec-' + id).classList.add('active');
  el.classList.add('active');
}}
function showTab(id, btn) {{
  btn.closest('.tab-row').querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  btn.closest('section, main').querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById(id).classList.add('active');
}}
</script>
</body>
</html>"""


def _css() -> str:
    return """
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    :root {
      --bg:#0f1117; --surface:#1a1d27; --card:#21253a; --border:#2e3347;
      --accent:#4f8ef7; --green:#3dd68c; --amber:#f5a623; --red:#f06565;
      --purple:#a78bfa; --teal:#2dd4bf; --muted:#8891a8; --text:#e2e8f0;
      --code-bg:#141720; --pill-r:6px;
    }
    body { font-family: "Inter", system-ui, sans-serif; background: var(--bg); color: var(--text); font-size: 14px; line-height: 1.6; }
    header { background: linear-gradient(135deg,#1e2340 0%,#162035 100%); border-bottom: 1px solid var(--border); padding: 28px 40px 22px; }
    header .badge { display:inline-block; font-size:11px; font-weight:600; letter-spacing:.05em; text-transform:uppercase; color:var(--accent); background:rgba(79,142,247,.12); border:1px solid rgba(79,142,247,.3); border-radius:4px; padding:2px 8px; margin-bottom:10px; }
    header h1 { font-size:22px; font-weight:700; margin-bottom:6px; }
    header .meta { color:var(--muted); font-size:13px; display:flex; gap:24px; flex-wrap:wrap; margin-top:8px; }
    header .meta .dot { width:6px; height:6px; border-radius:50%; background:var(--green); display:inline-block; }
    .layout { display:grid; grid-template-columns:220px 1fr; min-height:calc(100vh - 130px); }
    .sidebar { background:var(--surface); border-right:1px solid var(--border); padding:24px 0; position:sticky; top:0; height:calc(100vh - 130px); overflow-y:auto; }
    .sidebar h3 { font-size:10px; font-weight:700; letter-spacing:.1em; text-transform:uppercase; color:var(--muted); padding:0 20px 8px; }
    .nav-item { display:flex; align-items:center; gap:10px; padding:7px 20px; cursor:pointer; border-left:3px solid transparent; color:var(--muted); text-decoration:none; font-size:13px; transition:all .15s; }
    .nav-item:hover { color:var(--text); background:rgba(255,255,255,.04); }
    .nav-item.active { color:var(--text); border-left-color:var(--accent); background:rgba(79,142,247,.06); }
    .nav-item .icon { width:16px; text-align:center; }
    .nav-count { margin-left:auto; font-size:11px; background:var(--card); border:1px solid var(--border); border-radius:10px; padding:0 7px; color:var(--muted); }
    .nav-sep { border:none; border-top:1px solid var(--border); margin:12px 0; }
    main { padding:32px 36px; overflow-y:auto; }
    section { display:none; }
    section.active { display:block; }
    .section-heading { margin-bottom:24px; }
    .section-heading h2 { font-size:18px; font-weight:700; margin-bottom:4px; }
    .section-heading p { color:var(--muted); font-size:13px; }
    .summary-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(150px,1fr)); gap:14px; margin-bottom:32px; }
    .stat-card { background:var(--card); border:1px solid var(--border); border-radius:10px; padding:18px 20px; }
    .stat-card .label { font-size:11px; color:var(--muted); text-transform:uppercase; letter-spacing:.07em; margin-bottom:8px; }
    .stat-card .value { font-size:26px; font-weight:700; }
    .c-blue{color:var(--accent)} .c-green{color:var(--green)} .c-amber{color:var(--amber)} .c-purple{color:var(--purple)} .c-teal{color:var(--teal)}
    .entity-card { background:var(--card); border:1px solid var(--border); border-radius:10px; margin-bottom:14px; overflow:hidden; }
    .entity-card-header { display:flex; align-items:center; gap:12px; padding:14px 20px; border-bottom:1px solid var(--border); cursor:pointer; user-select:none; }
    .entity-card-header:hover { background:rgba(255,255,255,.03); }
    .entity-id { font-family:"JetBrains Mono","Fira Code",monospace; font-size:13px; font-weight:600; }
    .entity-type-pill { font-size:10px; font-weight:600; letter-spacing:.04em; border-radius:var(--pill-r); padding:2px 8px; border:1px solid; }
    .pill-sample  { color:var(--green);  background:rgba(61,214,140,.12);  border-color:rgba(61,214,140,.3); }
    .pill-run     { color:var(--accent); background:rgba(79,142,247,.12);  border-color:rgba(79,142,247,.3); }
    .pill-genome  { color:var(--purple); background:rgba(167,139,250,.12); border-color:rgba(167,139,250,.3); }
    .pill-action  { color:var(--amber);  background:rgba(245,166,35,.12);  border-color:rgba(245,166,35,.3); }
    .pill-software{ color:var(--teal);   background:rgba(45,212,191,.12);  border-color:rgba(45,212,191,.3); }
    .pill-release { color:var(--red);    background:rgba(240,101,101,.12); border-color:rgba(240,101,101,.3); }
    .pill-root    { color:var(--muted);  background:rgba(136,145,168,.12); border-color:rgba(136,145,168,.3); }
    .pill-file    { color:#e0c4ff;       background:rgba(224,196,255,.08); border-color:rgba(224,196,255,.25); }
    .chevron { margin-left:auto; color:var(--muted); font-size:12px; transition:transform .2s; }
    .entity-card.open .chevron { transform:rotate(90deg); }
    .entity-card-body { display:none; padding:0 20px 16px; }
    .entity-card.open .entity-card-body { display:block; }
    .prop-table { width:100%; border-collapse:collapse; margin-top:12px; }
    .prop-table td { padding:5px 8px; vertical-align:top; }
    .prop-table td:first-child { width:200px; color:var(--muted); font-size:12px; font-family:"JetBrains Mono",monospace; white-space:nowrap; }
    .prop-table td:last-child { font-size:13px; }
    .prop-table tr:nth-child(odd) td { background:rgba(255,255,255,.02); }
    code { font-family:"JetBrains Mono","Fira Code",monospace; font-size:12px; background:var(--code-bg); border:1px solid var(--border); border-radius:4px; padding:1px 5px; }
    .link-ref { font-family:monospace; font-size:12px; }
    .json-block { background:var(--code-bg); border:1px solid var(--border); border-radius:10px; padding:20px 24px; font-family:"JetBrains Mono","Fira Code",monospace; font-size:12px; line-height:1.7; overflow-x:auto; white-space:pre; color:#c9d1d9; }
    .tab-row { display:flex; gap:4px; margin-bottom:16px; border-bottom:1px solid var(--border); }
    .tab-btn { background:none; border:none; border-bottom:2px solid transparent; color:var(--muted); font-size:13px; padding:8px 14px; cursor:pointer; margin-bottom:-1px; }
    .tab-btn.active { color:var(--text); border-bottom-color:var(--accent); }
    .tab-panel { display:none; }
    .tab-panel.active { display:block; }
    .filter-summary { display:flex; flex-wrap:wrap; gap:16px; margin-top:28px; }
    .fs-section { background:var(--card); border:1px solid var(--border); border-radius:10px; padding:16px 20px; flex:1; min-width:220px; }
    .fs-heading { font-size:11px; font-weight:700; letter-spacing:.07em; text-transform:uppercase; color:var(--muted); margin-bottom:12px; display:flex; align-items:center; gap:8px; }
    .fs-badge { font-size:10px; font-weight:600; letter-spacing:.04em; border-radius:4px; padding:2px 7px; border:1px solid; }
    .badge-sample   { color:var(--green);  background:rgba(61,214,140,.12);  border-color:rgba(61,214,140,.3); }
    .badge-genome   { color:var(--purple); background:rgba(167,139,250,.12); border-color:rgba(167,139,250,.3); }
    .badge-abundance{ color:var(--amber);  background:rgba(245,166,35,.12);  border-color:rgba(245,166,35,.3); }
    .fs-table { width:100%; border-collapse:collapse; }
    .fs-label { color:var(--muted); font-size:12px; white-space:nowrap; padding:4px 12px 4px 0; width:140px; vertical-align:top; }
    .fs-value { font-size:13px; padding:4px 0; }
    .fs-none  { color:var(--muted); font-size:12px; font-style:italic; padding:4px 0; }
    """
