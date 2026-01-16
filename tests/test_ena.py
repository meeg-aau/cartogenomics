import unittest
import api_fetch.ena as ena
import logging
import sys

logging.basicConfig(level=logging.INFO, force=True, stream=sys.stdout)


class TestENA(unittest.TestCase):
    biosample_acc = "SAMN39868869"
    sample_acc = "SRS20505516"

    biosample_acc_multiple = "SAMEA114263416"
    sample_acc_multiple = "ERS16252355"

    expected_data = [
        {
            "ena_sample": "SRS20505516",
            "biosample": "SAMN39868869",
            "ena_run": "SRR28022638",
            "ena_experiment": "SRX23674624",
        }
    ]

    def test_get_accessions_by_biosample(self):
        logging.info(
            f"\nTesting get_accessions_by_sample with biosample {self.biosample_acc}"
        )
        data = ena.get_run_from_sample(self.biosample_acc)
        accessions = ena.get_accessions(data)
        assert accessions == self.expected_data

    def test_get_accessions_by_ena_sample(self):
        logging.info(
            f"\nTesting get_accessions_by_sample with ena sample {self.sample_acc}"
        )
        data = ena.get_run_from_sample(self.sample_acc)
        accessions = ena.get_accessions(data)
        assert accessions == self.expected_data

    def test_get_multiple_runs_for_one_biosample(self):
        logging.info(
            f"\n Testing get accessions for biosample with multiple experiments and runs {self.biosample_acc_multiple}"
        )
        data = ena.get_run_from_sample(self.biosample_acc_multiple)
        accessions = ena.get_accessions(data)
        assert len(accessions) == 4

    def test_get_multiple_runs_for_one_ena_sample(self):
        logging.info(
            f"\n Testing get accessions for ena_sample with multiple experiments and runs {self.sample_acc_multiple}"
        )
        data = ena.get_run_from_sample(self.sample_acc_multiple)
        accessions = ena.get_accessions(data)
        assert len(accessions) == 4


if __name__ == "__main__":
    unittest.main()
