import os
import tempfile
import zipfile

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Export a filtered set of samples and/or genomes as an RO-Crate zip"

    def add_arguments(self, parser):
        # --- Sample filters ---
        sample = parser.add_argument_group("Sample filters")
        sample.add_argument("--source-dataset", help='e.g. "MFD"')
        sample.add_argument(
            "--ontology",
            help='Substring match on Sample.ontology, e.g. "forest"',
        )

        #   Only one location filter (bbox / radius / country / polygon) at a time
        bbox_group = parser.add_argument_group("Bounding box filter")
        bbox_group.add_argument("--lat-min", type=float)
        bbox_group.add_argument("--lat-max", type=float)
        bbox_group.add_argument("--lon-min", type=float)
        bbox_group.add_argument("--lon-max", type=float)

        radius_group = parser.add_argument_group("Radius filter")
        radius_group.add_argument(
            "--near-lat", type=float, help="Latitude of center point for radius search"
        )
        radius_group.add_argument(
            "--near-lon", type=float, help="Longitude of center point for radius search"
        )
        radius_group.add_argument(
            "--radius-km",
            type=float,
            help="Radius in km around --near-lat/--near-lon (requires both)",
        )

        sample.add_argument(
            "--country-code",
            help=(
                'ISO 3166-1 alpha-2 country code, e.g. "DK" '
                "(matched against CountryBoundary)"
            ),
        )
        sample.add_argument(
            "--polygon",
            help="Arbitrary region as WKT or GeoJSON, e.g. 'POLYGON((...))'",
        )
        sample.add_argument(
            "--release-label",
            help='Restrict samples to a CartogenomicsRelease, e.g. "1.0"',
        )
        sample.add_argument(
            "--no-samples",
            action="store_true",
            help="Exclude samples from the crate",
        )
        sample.add_argument(
            "--no-runs",
            action="store_true",
            help="Exclude sequencing runs linked to the selected samples",
        )

        # --- Genome filters ---
        genome = parser.add_argument_group("Genome filters")
        genome.add_argument(
            "--include-genomes",
            action="store_true",
            help="Include Genome entities (independent of samples)",
        )
        genome.add_argument(
            "--genome-release-label",
            help='Restrict genomes to a CartogenomicsRelease, e.g. "1.0"',
        )
        genome.add_argument(
            "--min-completeness",
            type=float,
            help="Minimum genome completeness score (inclusive)",
        )
        genome.add_argument(
            "--max-contamination",
            type=float,
            help="Maximum genome contamination score (inclusive)",
        )

        # --- Output ---
        output = parser.add_argument_group("Output")
        output.add_argument(
            "--output",
            "-o",
            default="export.zip",
            help="Output zip file path (default: export.zip)",
        )
        output.add_argument(
            "--label",
            help="User preferred crate name. Auto-generated if not provided",
        )

    def handle(self, *args, **options):
        from rocrates.builder import build_crate

        self.stdout.write("Building RO-Crate …")

        try:
            crate = build_crate(
                label=options.get("label"),
                include_samples=not options["no_samples"],
                source_dataset=options.get("source_dataset"),
                ontology=options.get("ontology"),
                lat_min=options.get("lat_min"),
                lat_max=options.get("lat_max"),
                lon_min=options.get("lon_min"),
                lon_max=options.get("lon_max"),
                near_lat=options.get("near_lat"),
                near_lon=options.get("near_lon"),
                radius_km=options.get("radius_km"),
                country_code=options.get("country_code"),
                polygon=options.get("polygon"),
                release_label=options.get("release_label"),
                include_runs=not options["no_runs"],
                include_genomes=options["include_genomes"],
                genome_release_label=options.get("genome_release_label"),
                min_completeness=options.get("min_completeness"),
                max_contamination=options.get("max_contamination"),
            )
        except Exception as exc:
            raise CommandError(f"Failed to build crate: {exc}") from exc

        output_path = os.path.abspath(options["output"])

        with tempfile.TemporaryDirectory() as tmpdir:
            crate.write(tmpdir)
            with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for root, _, files in os.walk(tmpdir):
                    for fname in files:
                        abs_path = os.path.join(root, fname)
                        arc_name = os.path.relpath(abs_path, tmpdir)
                        zf.write(abs_path, arc_name)

        self.stdout.write(self.style.SUCCESS(f"RO-Crate written to {output_path}"))
