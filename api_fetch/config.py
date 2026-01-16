from pydantic import BaseModel, AnyHttpUrl


class BiosamplesConfig(BaseModel):
    sample_api_root: AnyHttpUrl = AnyHttpUrl("https://www.ebi.ac.uk/biosamples/samples")
    structured_data_api_root: AnyHttpUrl = AnyHttpUrl(
        "https://www.ebi.ac.uk/biosamples/structureddata"
    )


class ENAConfig(BaseModel):
    portal_api_root: AnyHttpUrl = AnyHttpUrl(
        "https://www.ebi.ac.uk/ena/portal/api/search?"
    )
    browser_api_root: AnyHttpUrl = AnyHttpUrl(
        "https://www.ebi.ac.uk/ena/browser/api/xml/"
    )
    run_query: str = "read_run"
    experiment_query: str = "read_experiment"
    retry_count: int = 3
    timeout: int = 30
    portal_api_output: dict = {"format": "json", "fields": ["all"]}

    # analysis_api: str = "analysis"  # TBC


class SRAConfig(BaseModel):
    api_root: AnyHttpUrl = AnyHttpUrl(
        "https://www.ebi.ac.uk/ebisearch/ws/rest/sra-experiment"
    )


class NCBIConfig(BaseModel):
    api_root: AnyHttpUrl = AnyHttpUrl("https://eutils.ncbi.nlm.nih.gov/entrez/eutils")


class BioStudies(BaseModel):
    api_root: AnyHttpUrl = AnyHttpUrl("https://www.ebi.ac.uk/biostudies/api/v1/studies")
