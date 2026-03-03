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
        self.browser_api_root = self.config.browser_api_root

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

    # def get_sample_accessions(self, acc: str) -> Dict[str, Optional[str]]:
    #     acc_type = get_accession_type(acc)
    #     result = []
    #     if acc_type == "run":
    #         result = self.get_request(
    #             {
    #                 "result": self.config.run_query,
    #                 "query": f"run_accession={acc}",
    #             }
    #         )
    #     elif acc_type == "experiment":
    #         result = self.get_request(
    #             {
    #                 "result": self.config.experiment_query,
    #                 "query": f"experiment_accession={acc}",
    #             }
    #         )
    #     elif acc_type in ["sample", "biosample"]:
    #         result = self.get_request(
    #             {
    #                 "result": self.config.sample_query,
    #                 "query": f"sample_accession={acc} OR secondary_sample_accession={acc}",
    #             }
    #         )
    #
    #     if not result:
    #         return {"biosample": None, "ena_sample": None}
    #
    #     # Take the first record to find sample accessions
    #     record = result[0]
    #     samples = [record.get("sample_accession"), record.get("secondary_sample_accession")]
    #     return {
    #         "biosample": next((i for i in samples if i and i.startswith("SAM")), None),
    #         "ena_sample": next(
    #             (i for i in samples if i and i.startswith(("ERS", "SRS", "DRS"))), None
    #         ),
    #     }

    def get_all_accessions(self, acc: str) -> List[Dict[str, Optional[str]]]:
        """
        Find all related accessions (run, experiment, biosample, ena_sample) starting from any.
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

        # We query the run result to get the full mapping
        run_data = self.get_request(
            {
                "result": self.config.run_query,
                "query": query,
            }
        )

        accessions = []
        for run in run_data:
            samples = [run.get("sample_accession"), run.get("secondary_sample_accession")]
            acc_dict = {
                "ena_run": run.get("run_accession"),
                "ena_experiment": run.get("experiment_accession"),
                "biosample": next((i for i in samples if i and i.startswith("SAM")), None),
                "ena_sample": next(
                    (i for i in samples if i and i.startswith(("ERS", "SRS", "DRS"))), None
                ),
            }
            accessions.append(acc_dict)
        return accessions

    def fetch_run_metadata(self, run_acc: str) -> List[Dict[str, Any]]:
        return self.get_request(
            {
                "result": self.config.run_query,
                "query": f"run_accession={run_acc}",
            }
        )

    def fetch_experiment_metadata(self, exp_acc: str) -> List[Dict[str, Any]]:
        return self.get_request(
            {
                "result": self.config.experiment_query,
                "query": f"experiment_accession={exp_acc}",
            }
        )

    def fetch_sample_metadata(self, sample_acc: str) -> List[Dict[str, Any]]:
        return self.get_request(
            {
                "result": self.config.sample_query,
                "query": f"sample_accession={sample_acc} OR secondary_sample_accession={sample_acc}",
            }
        )

#
# # Backward compatibility wrappers
#
#
# def run_to_sample(run_acc: str) -> Dict[str, Optional[str]]:
#     return ENAClient().get_all_accessions(run_acc)
#
#
# def experiment_to_sample(exp_acc: str) -> Dict[str, Optional[str]]:
#     return ENAClient().get_sample_accessions(exp_acc)
#
#
# def get_sample(acc: str) -> Dict[str, Optional[str]]:
#     return ENAClient().get_sample_accessions(acc)
#
#
# def get_request(data: Dict[str, Any]) -> List[Dict[str, Any]]:
#     return ENAClient().get_request(data)
#
#
# def get_sample_accession(acc: str) -> Dict[str, Optional[str]]:
#     return ENAClient().get_sample_accessions(acc)
#
#
# def get_run_from_sample(acc: str) -> List[Dict[str, Any]]:
#     client = ENAClient()
#     request_data = {
#         "result": client.config.run_query,
#         "query": f"sample_accession={acc} OR secondary_sample_accession={acc}",
#     }
#     return client.get_request(request_data)
#
#
# def get_experiment_from_sample(acc: str) -> List[Dict[str, Any]]:
#     client = ENAClient()
#     request_data = {
#         "result": client.config.experiment_query,
#         "query": f"sample_accession={acc} OR secondary_sample_accession={acc}",
#     }
#     return client.get_request(request_data)
#
#
# def get_accessions(run_data: List[Dict[str, Any]]) -> List[Dict[str, Optional[str]]]:
#     accessions = []
#     for run in run_data:
#         samples = [run.get("sample_accession"), run.get("secondary_sample_accession")]
#         acc_dict = {
#             "ena_run": run.get("run_accession"),
#             "ena_experiment": run.get("experiment_accession"),
#             "biosample": next((i for i in samples if i and i.startswith("SAM")), None),
#             "ena_sample": next(
#                 (i for i in samples if i and i.startswith(("ERS", "SRS", "DRS"))), None
#             ),
#         }
#         accessions.append(acc_dict)
#     return accessions
