"""
Tests for the CORDIS EU grant extractor.

All tests use mock data — no real HTTP calls are made.
CORDIS servers may be geo-restricted; tests must work offline.

To run:
    pytest tests/test_cordis_extractor.py -v
"""

import pytest
from datetime import date

from exceptions import APIResponseError, DataExtractionError
from extractors.cordis import CORDISExtractor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_extractor(target_date=None):
    """Return a CORDISExtractor with a fixed date so tests are deterministic."""
    return CORDISExtractor(target_date=target_date or date(2025, 1, 10))


def make_response(projects: list, total: int) -> dict:
    """Build a fake CORDIS API response with the given projects list."""
    return {
        "data": {
            "projects": {
                "project": projects,
                "totalCount": total,
            }
        }
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_project():
    """A realistic fake CORDIS project record with all expected fields."""
    return {
        "id": "101000413",
        "title": "Quantum Computing for Climate Modelling",
        "startDate": "2021-03-01",
        "endDate": "2024-02-28",
        "ecMaxContribution": "3500000.00",
        "totalCost": "4200000.00",
        "contentUpdateDate": "2025-01-10",
        "relations": {
            "associations": {
                "organization": [
                    {
                        "name": "UNIVERSITY OF AMSTERDAM",
                        "shortName": "UVA",
                        "country": "NL",
                        "role": "coordinator",
                    },
                    {
                        "name": "OXFORD UNIVERSITY",
                        "shortName": "OX",
                        "country": "GB",
                        "role": "participant",
                    },
                ]
            }
        },
    }


@pytest.fixture
def sample_cordis_response(sample_project):
    """A valid CORDIS API response containing one project."""
    return make_response([sample_project], total=1)


@pytest.fixture
def empty_cordis_response():
    """A valid CORDIS response with zero results."""
    return make_response([], total=0)


# ---------------------------------------------------------------------------
# test_source_name
# ---------------------------------------------------------------------------

def test_source_name():
    """source_name must return 'CORDIS' — used in the output filename."""
    assert make_extractor().source_name == "CORDIS"


# ---------------------------------------------------------------------------
# test_get_total_count
# ---------------------------------------------------------------------------

def test_get_total_count(sample_cordis_response):
    """get_total_count should read totalCount from the nested data block."""
    assert make_extractor().get_total_count(sample_cordis_response) == 1


def test_get_total_count_missing_key_raises():
    """get_total_count must raise APIResponseError if structure is wrong."""
    extractor = make_extractor()
    with pytest.raises(APIResponseError):
        extractor.get_total_count({"wrong": "structure"})


# ---------------------------------------------------------------------------
# test_parse_records — happy path
# ---------------------------------------------------------------------------

def test_parse_records_returns_correct_count(sample_cordis_response):
    """parse_records should return one record per project in the response."""
    records = make_extractor().parse_records(sample_cordis_response)
    assert len(records) == 1


def test_parse_records_column_keys(sample_cordis_response):
    """Every record must have exactly the 9 required output columns."""
    records = make_extractor().parse_records(sample_cordis_response)
    expected_keys = {
        "FIRST", "LAST", "INSTITUTION", "TITLE",
        "FUNDING_AMT", "CURRENCY", "AWARD_DATE", "SOURCE", "LINK",
    }
    assert set(records[0].keys()) == expected_keys


def test_parse_records_field_values(sample_cordis_response):
    """Fields should be mapped correctly from the raw API response."""
    record = make_extractor().parse_records(sample_cordis_response)[0]

    assert record["TITLE"] == "Quantum Computing for Climate Modelling"
    assert record["INSTITUTION"] == "UNIVERSITY OF AMSTERDAM"
    assert record["FUNDING_AMT"] == "3500000.00"
    assert record["CURRENCY"] == "EUR"
    assert record["AWARD_DATE"] == "2021-03-01"
    assert record["SOURCE"] == "CORDIS"
    assert record["LINK"] == "https://cordis.europa.eu/project/id/101000413"


def test_parse_records_first_last_empty(sample_cordis_response):
    """FIRST and LAST must be empty strings — CORDIS has no PI name field."""
    record = make_extractor().parse_records(sample_cordis_response)[0]
    assert record["FIRST"] == ""
    assert record["LAST"] == ""


# ---------------------------------------------------------------------------
# test_coordinator_extraction
# ---------------------------------------------------------------------------

def test_coordinator_is_preferred_over_participant():
    """When multiple orgs exist, the coordinator role should be selected."""
    extractor = make_extractor()
    raw = {
        "id": "111",
        "title": "Test",
        "ecMaxContribution": "100000",
        "startDate": "2025-01-01",
        "relations": {
            "associations": {
                "organization": [
                    {"name": "PARTICIPANT ORG", "role": "participant"},
                    {"name": "COORDINATOR ORG", "role": "coordinator"},
                ]
            }
        },
    }
    record = extractor._map_record(raw)
    assert record["INSTITUTION"] == "COORDINATOR ORG"


def test_single_org_as_dict_not_list():
    """CORDIS sometimes returns a single org as a dict instead of a list."""
    extractor = make_extractor()
    raw = {
        "id": "222",
        "title": "Test",
        "ecMaxContribution": "50000",
        "startDate": "2025-01-01",
        "relations": {
            "associations": {
                "organization": {     # dict, not list
                    "name": "SINGLE ORG",
                    "role": "coordinator",
                }
            }
        },
    }
    record = extractor._map_record(raw)
    assert record["INSTITUTION"] == "SINGLE ORG"


def test_no_org_returns_empty_institution():
    """If organisations block is absent, INSTITUTION should be ''."""
    extractor = make_extractor()
    raw = {
        "id": "333",
        "title": "No Org Grant",
        "ecMaxContribution": "10000",
        "startDate": "2025-01-01",
        # no relations key
    }
    record = extractor._map_record(raw)
    assert record["INSTITUTION"] == ""


# ---------------------------------------------------------------------------
# test_single_result_as_dict
# ---------------------------------------------------------------------------

def test_single_result_wrapped_as_dict():
    """
    CORDIS API sometimes returns a single project as a dict instead of a list.
    parse_records must handle both cases.
    """
    extractor = make_extractor()
    response = {
        "data": {
            "projects": {
                # dict instead of list — API quirk for single results
                "project": {
                    "id": "999",
                    "title": "Single Project",
                    "ecMaxContribution": "200000",
                    "startDate": "2025-01-01",
                    "relations": {"associations": {"organization": []}},
                },
                "totalCount": 1,
            }
        }
    }
    records = extractor.parse_records(response)
    assert len(records) == 1
    assert records[0]["TITLE"] == "Single Project"


# ---------------------------------------------------------------------------
# test_empty and error cases
# ---------------------------------------------------------------------------

def test_empty_response_returns_empty_list(empty_cordis_response):
    """parse_records on a zero-result response should return an empty list."""
    records = make_extractor().parse_records(empty_cordis_response)
    assert records == []


def test_parse_records_missing_key_raises():
    """parse_records must raise APIResponseError if structure is wrong."""
    extractor = make_extractor()
    with pytest.raises(APIResponseError):
        extractor.parse_records({"wrong": "structure"})


def test_bad_record_skipped_rest_continues():
    """A record raising DataExtractionError should be skipped, not crash."""
    extractor = make_extractor()
    good = {
        "FIRST": "", "LAST": "", "INSTITUTION": "MIT",
        "TITLE": "Good", "FUNDING_AMT": "100000", "CURRENCY": "EUR",
        "AWARD_DATE": "2025-01-01", "SOURCE": "CORDIS",
        "LINK": "https://cordis.europa.eu/project/id/1",
    }

    call_count = {"n": 0}

    def fake_map(raw):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise DataExtractionError("Simulated bad record")
        return good

    extractor._map_record = fake_map

    response = make_response([{"id": "1"}, {"id": "2"}], total=2)
    records = extractor.parse_records(response)

    assert len(records) == 1
    assert records[0]["INSTITUTION"] == "MIT"
