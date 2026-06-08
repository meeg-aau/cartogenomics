class BiosamplesConfig:
    sample_api_root: str = "https://www.ebi.ac.uk/biosamples/samples"
    structured_data_api_root: str = "https://www.ebi.ac.uk/biosamples/structureddata"


class ENAConfig:
    portal_api_root: str = "https://www.ebi.ac.uk/ena/portal/api/search?"
    run_query: str = "read_run"
    sample_query: str = "sample"
    genome_query: str = "wgs_set"
    retry_count: int = 3
    timeout: int = 30
    portal_api_output: dict = {
        "format": "json",
        "fields": ["all"]
    }
    run_fields: list = [
        "run_accession",
        "experiment_accession",
        "sample_accession",
        "secondary_sample_accession",
        "read_count",
        "first_created",
        "last_updated",
        "fastq_ftp",
        "library_source",
        "library_strategy",
        "instrument_model",
        "instrument_platform"
    ]
    genome_fields: list = [
        "assembly_accession",
        "sample_accession",
        "secondary_sample_accession",
        "first_created",
        "last_updated",
        "set_fasta_ftp",
    ]
    ACCESSION_PREFIXES = {
        "RR": "run",
        "RX": "experiment",
        "RS": "sample",
        "SAM": "biosample",
        "GCA": "genome"
    }


class SRAConfig:
    api_root: str = "https://www.ebi.ac.uk/ebisearch/ws/rest/sra-experiment"


class NCBIConfig:
    api_root: str = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


class BioStudies:
    api_root: str = "https://www.ebi.ac.uk/biostudies/api/v1/studies"
