from typing import List, Dict, Optional, Any

import requests
import api_fetch.config as config
from api_fetch.constants import ACCESSION_PREFIXES


def get_accession_type(acc: str) -> Optional[str]:
    for prefix, acc_type in ACCESSION_PREFIXES.items():
        if prefix in acc:
            return acc_type
    return None


class ENAClient:
    def __init__(self, api_config: config.ENAConfig = None):
        self.config = api_config or config.ENAConfig()
        self.portal_api_root = self.config.portal_api_root

    def get_request(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        retry = 0
        params = data.copy()
        params.update(self.config.portal_api_output)
        while retry < self.config.retry_count:
            try:
                response = requests.get(
                    url=str(self.portal_api_root),
                    params=params,
                    timeout=self.config.timeout,
                )
                if response.ok:
                    return response.json()
            except requests.exceptions.RequestException:
                pass
            retry += 1
        return []

    def get_all_run_accessions(self, acc: str) -> Dict[str, Optional[str]]:
        """
        Find all related accessions (run, experiment, biosample, ena_sample) starting from any.
        """
        acc_type = get_accession_type(acc)
        if acc_type == "run":
            query = f"run_accession={acc}"
            result = self.config.run_query
        elif acc_type == "experiment":
            query = f"experiment_accession={acc}"
            result = self.config.experiment_query
        elif acc_type in ["sample", "biosample"]:
            query = f"sample_accession={acc} OR secondary_sample_accession={acc}"
            result = self.config.sample_query
        else:
            return {}

        # query the run result to get the full mapping
        ena_data = self.get_request(
            {
                "result": result,
                "query": query,
                "fields": ["all"],
            }
        )

        ena_metadata = ena_data[0]
        samples = [ena_metadata.get("sample_accession"), ena_metadata.get("secondary_sample_accession")]
        acc_dict = {
            "ena_run": ena_metadata.get("run_accession"),
            "ena_experiment": ena_metadata.get("experiment_accession"),
            "biosample": next((i for i in samples if i and i.startswith("SAM")), None),
            "ena_sample": next(
                (i for i in samples if i and i.startswith(("ERS", "SRS", "DRS"))), None
            ),
        }

        return acc_dict

    def fetch_run_metadata(self, run_acc: str) -> Dict[str, Any]:
        ena_data =  self.get_request(
            {
                "result": self.config.run_query,
                "query": f"run_accession={run_acc}",
            }
        )
        run_data = {}
        for field in self.config.run_fields:
            run_data[field] = ena_data[0].get(field)
        return run_data

    def get_all_genome_accessions(self, acc: str) -> Dict[str, Any]:
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


