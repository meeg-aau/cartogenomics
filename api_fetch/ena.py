from typing import List, Dict, Optional, Any
import requests
import api_fetch.config as config



def get_accession_type(acc: str) -> Optional[str]:
    for prefix, acc_type in config.ENAConfig.ACCESSION_PREFIXES.items():
        if prefix in acc:
            return acc_type
    return None


class ENAClient:
    def __init__(self, api_config: config.ENAConfig = None):
        self.config = api_config

    def get_request(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        retry = 0
        params = data
        params.update(self.config.portal_api_output)
        while retry < self.config.retry_count:
            try:
                response = requests.get(
                    url=self.config.portal_api_root,
                    params=params,
                    timeout=self.config.timeout,
                )
                #   need to update with known error response codes
                if response.ok:
                    return response.json()
            except requests.exceptions.RequestException:
                pass
            retry += 1
        return []

    def get_all_run_accessions(self, acc: str) -> List[Dict[str, Any]]:
        """
        Return all runs associated with any ENA accession (run, experiment, biosample, sample).
        """
        acc_type = get_accession_type(acc)
        if acc_type == "run":
            query = f"run_accession={acc}"
        elif acc_type == "experiment":
            query = f"experiment_accession={acc}"
        elif acc_type in ["sample", "biosample"]:
            query = f"sample_accession={acc} OR secondary_sample_accession={acc}"
        else:
            return []

        ena_data = self.get_request({
            "result": self.config.run_query,
            "query": query,
            "fields": self.config.run_fields,
        })

        results = []
        for record in ena_data:
            samples = [record.get("sample_accession"), record.get("secondary_sample_accession")]
            results.append({
                "run_accession": record.get("run_accession"),
                "experiment_accession": record.get("experiment_accession"),
                "biosample": next((i for i in samples if i and i.startswith("SAM")), None),
                "ena_sample": next((i for i in samples if i and i.startswith(("ERS", "SRS", "DRS"))), None),
                "read_count": record.get("read_count"),
                "first_created": record.get("first_created"),
                "last_updated": record.get("last_updated"),
                "fastq_ftp": record.get("fastq_ftp"),
                "library_source": record.get("library_source"),
                "library_strategy": record.get("library_strategy"),
                "instrument_model": record.get("instrument_model"),
                "instrument_platform": record.get("instrument_platform"),
            })
        return results

    def get_all_genome_accessions(self, acc: str) -> Dict[str, Any]:
        """
        Return all genomes associated with an accession - genome, sample, biosample
        """
        acc_type = get_accession_type(acc)
        fields = self.config.genome_fields

        if acc_type == "sample" or acc_type == "biosample":
            query = f"sample_accession={acc} OR secondary_sample_accession={acc}"
        elif acc_type == "genome":
            query = f"assembly_accession={acc}"
        else:
            return {}

        ena_data = self.get_request(
            {
                "result": self.config.genome_query,
                "query": query,
                "fields": fields,
            }
        )

        if not ena_data:
            return {}

        record = ena_data[0]
        samples = [record.get("sample_accession"), record.get("secondary_sample_accession")]
        return {
            "genome_accession": record.get("assembly_accession") if acc_type != "genome" else acc,
            "biosample": next((i for i in samples if i and i.startswith("SAM")), None),
            "ena_sample": next((i for i in samples if i and i.startswith(("ERS", "SRS", "DRS"))), None),
            "first_created": record.get("first_created"),
            "last_updated": record.get("last_updated"),
        }


