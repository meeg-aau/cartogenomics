import unittest
import api_fetch.biosamples as biosamples
import logging

import sys

logging.basicConfig(level=logging.INFO, force=True, stream=sys.stdout)


class TestBioSamples(unittest.TestCase):
    biosample_acc = "SAMN39868869"

    def test_get_biosamples_data(self):
        logging.info(f"\nTesting fetch data from biosamples")
        biosamples_json = biosamples.get_basic_sample_data(self.biosample_acc)
        assert len(biosamples_json) > 0
        assert biosamples_json["accession"] == "SAMN39868869"
        assert biosamples_json["name"] == "MFD04522"
