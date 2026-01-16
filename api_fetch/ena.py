from typing import List, Dict

import requests
import api_fetch.config as config


api_config = config.ENAConfig()

PORTAL_API_ROOT = api_config.portal_api_root
BROWSER_API_ROOT = api_config.browser_api_root

RETRY_COUNT = 3


def get_request(data: Dict) -> Dict:
    retry = 0
    data.update(api_config.portal_api_output)
    while retry < api_config.retry_count:
        try:
            response = requests.get(
                url=str(PORTAL_API_ROOT), params=data, timeout=api_config.timeout
            )
            if response.ok:
                return response.json()
        except requests.exceptions.RequestException as e:
            pass
        retry += 1
    return {}


def get_run_from_sample(acc: str) -> Dict:
    request_data = {
        "result": f"{api_config.run_query}",
        "query": f"sample_accession={acc} OR secondary_sample_accession={acc}",
    }
    run_data = get_request(request_data)
    # add data curation tool here
    if not run_data:
        return {}
    return run_data


def get_experiment_from_sample(acc: str) -> Dict:
    request_data = {
        "result": f"{api_config.experiment_query}",
        "query": f"sample_accession={acc} OR secondary_sample_accession={acc}",
    }
    experiment_data = get_request(request_data)
    # add data curation tool here
    if not experiment_data:
        return {}
    return experiment_data


def get_accessions(run_data: Dict) -> List:
    accessions = []
    if not len(run_data):
        return accessions
    for run in run_data:
        samples = [run["sample_accession"], run["secondary_sample_accession"]]

        acc_dict = {
            "ena_run": run["run_accession"],
            "ena_experiment": run["experiment_accession"],
            "biosample": next((i for i in samples if i.startswith("SAM")), None),
            "ena_sample": next((i for i in samples if "RS" in i), None),
        }
        accessions.append(acc_dict)
    return accessions
