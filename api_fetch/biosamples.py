import logging
from json import JSONDecodeError
from typing import Dict

import requests

import api_fetch.config as config

api_config = config.BiosamplesConfig()

"""fetch a sample and any existing structured data for a given sample accession from EBI BioSamples API"""

BASE_URL = api_config.sample_api_root

def get_basic_sample_data(sample: str) -> Dict:

    logging.info(f"Fetching {sample} from Biosamples")

    response = requests.get(f"{BASE_URL}/{sample}")
    if response.status_code == requests.codes.not_found:
        logging.info(f"No biosample for sample {sample}")
        return {}
    try:
        data = response.json()
    except (JSONDecodeError, KeyError, AttributeError) as e:
        logging.error("Could not read response from biosamples")
        raise e

    return data

