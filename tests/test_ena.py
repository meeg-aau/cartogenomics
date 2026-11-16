import logging
import sys
import unittest
from unittest.mock import patch

from api_fetch.ena import ENAClient, get_accession_type

logging.basicConfig(level=logging.INFO, force=True, stream=sys.stdout)


MOCK_RUN_RECORD = {
    "run_accession": "ERR123456",
    "experiment_accession": "ERX123456",
    "sample_accession": "SAMEA654321",
    "secondary_sample_accession": "ERS654321",
}

MOCK_GENOME_RECORD = {
    "assembly_accession": "GCA_031587420.1",
    "sample_accession": "SAMEA112438701",
    "secondary_sample_accession": "ERS13041822",
    "first_created": "2023-11-01",
    "last_updated": "2024-02-10",
}


class TestGetAccessionType(unittest.TestCase):

    def test_run(self):
        logging.info("\nTesting accession type: run")
        assert get_accession_type("ERR123456") == "run"

    def test_experiment(self):
        logging.info("\nTesting accession type: experiment")
        assert get_accession_type("ERX123456") == "experiment"

    def test_ena_sample(self):
        logging.info("\nTesting accession type: ena sample")
        assert get_accession_type("ERS123456") == "sample"

    def test_biosample(self):
        logging.info("\nTesting accession type: biosample")
        assert get_accession_type("SAMEA123456") == "biosample"

    def test_genome(self):
        logging.info("\nTesting accession type: genome")
        assert get_accession_type("GCA_123456.1") == "genome"

    def test_unknown(self):
        logging.info("\nTesting accession type: unknown")
        assert get_accession_type("UNKNOWN123") is None


class TestGetAllRunAccessions(unittest.TestCase):
    client = ENAClient()

    @patch("api_fetch.ena.ENAClient.get_request")
    def test_from_run_accession(self, mock_get):
        logging.info("\nTesting get_all_run_accessions from run accession")
        mock_get.return_value = [MOCK_RUN_RECORD]
        result = self.client.get_all_run_accessions("ERR123456")
        assert len(result) == 1
        assert result[0]["run_accession"] == "ERR123456"
        assert result[0]["experiment_accession"] == "ERX123456"
        assert result[0]["biosample"] == "SAMEA654321"
        assert result[0]["ena_sample"] == "ERS654321"

    @patch("api_fetch.ena.ENAClient.get_request")
    def test_from_biosample_accession(self, mock_get):
        logging.info("\nTesting get_all_run_accessions from biosample accession")
        mock_get.return_value = [MOCK_RUN_RECORD]
        result = self.client.get_all_run_accessions("SAMEA654321")
        assert result[0]["biosample"] == "SAMEA654321"
        assert result[0]["ena_sample"] == "ERS654321"

    @patch("api_fetch.ena.ENAClient.get_request")
    def test_biosample_in_secondary_field(self, mock_get):
        logging.info(
            "\nTesting get_all_run_accessions with biosample in "
            "secondary_sample_accession"
        )
        mock_get.return_value = [
            {
                "run_accession": "ERR123456",
                "experiment_accession": "ERX123456",
                "sample_accession": "ERS654321",
                "secondary_sample_accession": "SAMEA654321",
            }
        ]
        result = self.client.get_all_run_accessions("ERR123456")
        assert result[0]["biosample"] == "SAMEA654321"
        assert result[0]["ena_sample"] == "ERS654321"

    @patch("api_fetch.ena.ENAClient.get_request")
    def test_multiple_runs_returned(self, mock_get):
        logging.info(
            "\nTesting get_all_run_accessions returns all runs for a biosample"
        )
        mock_get.return_value = [
            {**MOCK_RUN_RECORD, "run_accession": "ERR111111"},
            {**MOCK_RUN_RECORD, "run_accession": "ERR222222"},
        ]
        result = self.client.get_all_run_accessions("SAMEA654321")
        assert len(result) == 2
        assert result[0]["run_accession"] == "ERR111111"
        assert result[1]["run_accession"] == "ERR222222"

    def test_unknown_accession_returns_empty(self):
        logging.info("\nTesting get_all_run_accessions with unknown accession")
        result = self.client.get_all_run_accessions("UNKNOWN123")
        assert result == []


class TestGetAllGenomeAccessions(unittest.TestCase):
    client = ENAClient()

    @patch("api_fetch.ena.ENAClient.get_request")
    def test_from_genome_accession(self, mock_get):
        logging.info("\nTesting get_all_genome_accessions from genome accession")
        mock_get.return_value = [MOCK_GENOME_RECORD]
        result = self.client.get_all_genome_accessions("GCA_031587420.1")
        assert result["genome_accession"] == "GCA_031587420.1"
        assert result["biosample"] == "SAMEA112438701"
        assert result["ena_sample"] == "ERS13041822"
        assert result["first_created"] == "2023-11-01"
        assert result["last_updated"] == "2024-02-10"

    @patch("api_fetch.ena.ENAClient.get_request")
    def test_from_biosample_accession(self, mock_get):
        logging.info("\nTesting get_all_genome_accessions from biosample accession")
        mock_get.return_value = [MOCK_GENOME_RECORD]
        result = self.client.get_all_genome_accessions("SAMEA112438701")
        assert result["genome_accession"] == "GCA_031587420.1"
        assert result["biosample"] == "SAMEA112438701"
        assert result["first_created"] == "2023-11-01"

    @patch("api_fetch.ena.ENAClient.get_request")
    def test_genome_fields_are_requested(self, mock_get):
        logging.info("\nTesting get_all_genome_accessions requests explicit fields")
        mock_get.return_value = [MOCK_GENOME_RECORD]
        self.client.get_all_genome_accessions("GCA_031587420.1")
        call_kwargs = mock_get.call_args[0][0]
        assert "fields" in call_kwargs
        assert "first_created" in call_kwargs["fields"]
        assert "last_updated" in call_kwargs["fields"]
        assert "assembly_accession" in call_kwargs["fields"]

    @patch("api_fetch.ena.ENAClient.get_request")
    def test_empty_response_returns_empty(self, mock_get):
        logging.info("\nTesting get_all_genome_accessions with empty response")
        mock_get.return_value = []
        result = self.client.get_all_genome_accessions("GCA_031587420.1")
        assert result == {}

    def test_unknown_accession_returns_empty(self):
        logging.info("\nTesting get_all_genome_accessions with unknown accession")
        result = self.client.get_all_genome_accessions("UNKNOWN123")
        assert result == {}


if __name__ == "__main__":
    unittest.main()
