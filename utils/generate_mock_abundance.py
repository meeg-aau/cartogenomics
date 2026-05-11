"""
Generate a mock genome × run abundance Parquet file for development and testing.

Output shape: 4000 genomes (rows) × 10,000 runs (columns), or real accessions from CSVs
Values:       relative abundance as float32 in [0, 1]
Sparsity:     ~90% zeros (realistic for metagenomic data)
Index:        genome_id (GCA accessions)
Columns:      run accessions (ERR/SRR)

Usage:
    python utils/generate_mock_abundance.py
    python utils/generate_mock_abundance.py --output /path/to/file.parquet
    python utils/generate_mock_abundance.py --genomes 500 --runs 1000 --sparsity 0.85
    python utils/generate_mock_abundance.py \
        --genome-accessions genome_accessions.csv \
        --run-accessions run_accessions.csv \
        --tsv
"""

import argparse
import logging
import time

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)


def parse_args():
    parser = argparse.ArgumentParser(description="Generate mock abundance Parquet file")
    parser.add_argument("--output", "-o", default="mock_abundance.parquet", help="Output Parquet file path")
    parser.add_argument("--genomes", type=int, default=4000, help="Number of genome rows (ignored if --genome-accessions given)")
    parser.add_argument("--runs", type=int, default=10000, help="Number of run columns (ignored if --run-accessions given)")
    parser.add_argument("--genome-accessions", help="CSV file of real genome accessions (one per line, no header)")
    parser.add_argument("--run-accessions", help="CSV file of real run accessions (one per line, no header)")
    parser.add_argument("--sparsity", type=float, default=0.90, help="Fraction of zero values (0–1)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility")
    parser.add_argument("--tsv", action="store_true", help="Also write a TSV copy alongside the Parquet file")
    return parser.parse_args()


def load_accessions_from_csv(path: str) -> list:
    with open(path) as f:
        return [line.strip() for line in f if line.strip()]


def generate_accessions(n_genomes: int, n_runs: int):
    genomes = [f"GCA_{str(i).zfill(9)}.1" for i in range(1, n_genomes + 1)]
    runs = [f"ERR{str(i).zfill(8)}" for i in range(10000001, 10000001 + n_runs)]
    return genomes, runs


def generate_matrix(n_genomes: int, n_runs: int, sparsity: float, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    logger.info(f"Generating {n_genomes} × {n_runs} matrix ({sparsity:.0%} sparse)")
    t0 = time.time()

    matrix = rng.random((n_genomes, n_runs), dtype=np.float32)
    # Zero out cells according to sparsity
    matrix[rng.random((n_genomes, n_runs)) < sparsity] = 0.0

    non_zero = np.count_nonzero(matrix)
    total = n_genomes * n_runs
    logger.info(f"Matrix generated in {time.time() - t0:.2f}s — {non_zero:,} non-zero values ({non_zero/total:.1%})")
    return matrix


def write_parquet(matrix: np.ndarray, genomes: list, runs: list, output: str):
    logger.info(f"Building DataFrame")
    t0 = time.time()
    df = pd.DataFrame(matrix, index=genomes, columns=runs)
    df.index.name = "genome_id"

    logger.info(f"Writing Parquet to {output}")
    table = pa.Table.from_pandas(df)
    pq.write_table(table, output, compression="snappy")

    size_mb = table.nbytes / 1024 / 1024
    logger.info(f"Done in {time.time() - t0:.2f}s — uncompressed size ~{size_mb:.1f} MB")
    return df


def write_tsv(df: pd.DataFrame, output: str):
    logger.info(f"Writing TSV to {output}")
    t0 = time.time()
    df.to_csv(output, sep="\t")
    logger.info(f"TSV written in {time.time() - t0:.2f}s")


def main():
    args = parse_args()
    t_start = time.time()

    if args.genome_accessions:
        genomes = load_accessions_from_csv(args.genome_accessions)
        logger.info(f"Loaded {len(genomes)} genome accessions from {args.genome_accessions}")
    else:
        genomes, _ = generate_accessions(args.genomes, args.runs)

    if args.run_accessions:
        runs = load_accessions_from_csv(args.run_accessions)
        logger.info(f"Loaded {len(runs)} run accessions from {args.run_accessions}")
    else:
        _, runs = generate_accessions(args.genomes, args.runs)

    n_genomes, n_runs = len(genomes), len(runs)
    matrix = generate_matrix(n_genomes, n_runs, args.sparsity, args.seed)
    df = write_parquet(matrix, genomes, runs, args.output)

    if args.tsv:
        tsv_path = args.output.replace(".parquet", ".tsv")
        write_tsv(df, tsv_path)

    logger.info(f"Total time: {time.time() - t_start:.2f}s → {args.output}")


if __name__ == "__main__":
    main()
