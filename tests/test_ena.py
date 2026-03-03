import unittest
from unittest.mock import patch
import api_fetch.ena as ena
import logging
import sys

logging.basicConfig(level=logging.INFO, force=True, stream=sys.stdout)


class TestENA(unittest.TestCase):
    biosample_acc = "SAMN39868869"
    sample_acc = "SRS20505516"

    biosample_acc_multiple = "SAMEA114263416"
    sample_acc_multiple = "ERS16252355"

    run_accession = "SRR28022638"
    experiment_accession = "SRX23674624"

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

    def test_get_sample_from_experiment(self):
        logging.info(f"\n Testing get sample from experiment {self.sample_acc}")
        sample_dict = ena.experiment_to_sample(self.experiment_accession)
        assert sample_dict == {"biosample": self.biosample_acc, "ena_sample": self.sample_acc}

    def test_get_sample_from_run(self):
        logging.info(f"\n Testing get sample from run {self.sample_acc}")
        sample_dict = ena.run_to_sample(self.run_accession)
        assert sample_dict == {"biosample": self.biosample_acc, "ena_sample": self.sample_acc}

    def test_client_get_all_accessions_from_run(self):
        logging.info(f"\n Testing ENAClient.get_all_accessions from run {self.run_accession}")
        client = ena.ENAClient()
        accessions = client.get_all_accessions(self.run_accession)
        assert accessions == self.expected_data

    def test_client_fetch_metadata(self):
        logging.info(f"\n Testing ENAClient.fetch metadata methods")
        client = ena.ENAClient()
        # Just check they can be called and return something (mocked in tests maybe, but here it's real calls)
        # In a real test we would mock the response.
        run_meta = client.fetch_run_metadata(self.run_accession)
        assert len(run_meta) > 0
        exp_meta = client.fetch_experiment_metadata(self.experiment_accession)
        assert len(exp_meta) > 0
        sample_meta = client.fetch_sample_metadata(self.sample_acc)
        assert len(sample_meta) > 0

    @patch("api_fetch.ena.ENAClient.get_request")
    def test_run_to_sample_fallback(self, mock_get_request):
        # Case: BioSample accession is in secondary_sample_accession
        mock_get_request.return_value = [
            {"sample_accession": "SRS12345", "secondary_sample_accession": "SAMN12345"}
        ]
        sample_dict = ena.run_to_sample("ERR12345")
        assert sample_dict == {"biosample": "SAMN12345", "ena_sample": "SRS12345"}

    @patch("api_fetch.ena.ENAClient.get_request")
    def test_run_to_sample_no_biosample(self, mock_get_request):
        # Case: No BioSample accession in either field
        mock_get_request.return_value = [
            {"sample_accession": "", "secondary_sample_accession": "ERS12345"}
        ]
        sample_dict = ena.run_to_sample("ERR12345")
        assert sample_dict == {"biosample": None, "ena_sample": "ERS12345"}

    @patch("api_fetch.ena.ENAClient.get_request")
    def test_experiment_to_sample_fallback(self, mock_get_request):
        # Case: BioSample accession is in secondary_sample_accession for experiment
        mock_get_request.return_value = [
            {"sample_accession": "SRS12345", "secondary_sample_accession": "SAMN12345"}
        ]
        sample_dict = ena.experiment_to_sample("ERX12345")
        assert sample_dict == {"biosample": "SAMN12345", "ena_sample": "SRS12345"}

    @patch("api_fetch.ena.ENAClient.get_request")
    def test_experiment_to_sample_no_biosample(self, mock_get_request):
        # Case: No BioSample accession in either field for experiment
        mock_get_request.return_value = [
            {"sample_accession": "", "secondary_sample_accession": "ERS12345"}
        ]
        sample_dict = ena.experiment_to_sample("ERX12345")
        assert sample_dict == {"biosample": None, "ena_sample": "ERS12345"}

if __name__ == "__main__":
    unittest.main()
