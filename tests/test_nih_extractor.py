"""
Tests for the NIH RePORTER extractor.

We test the data parsing and mapping logic only — no real HTTP calls.
This keeps tests fast and reliable (they don't depend on the internet).

To run:
    pytest tests/
    pytest tests/ -v          # verbose output
    pytest tests/ -v -s       # also show print statements
"""

import pytest
from datetime import date

from exceptions import APIResponseError, DataExtractionError
from extractors.nih import NIHExtractor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_extractor(target_date=None):
    """Return an NIHExtractor with a fixed date so tests are deterministic."""
    return NIHExtractor(target_date=target_date or date(2025, 1, 10))


# ---------------------------------------------------------------------------
# test_source_name
# ---------------------------------------------------------------------------

def test_source_name():
    """source_name must return 'NIH' — used in the output filename."""
    extractor = make_extractor()
    assert extractor.source_name == "NIH"


# ---------------------------------------------------------------------------
# test_get_total_count
# ---------------------------------------------------------------------------

def test_get_total_count(sample_nih_response):
    """get_total_count should read the total from meta.total."""
    extractor = make_extractor()
    assert extractor.get_total_count(sample_nih_response) == 2


def test_get_total_count_missing_key_raises():
    """get_total_count must raise APIResponseError if meta key is absent."""
    extractor = make_extractor()
    bad_response = {"data": []}  # wrong structure

    with pytest.raises(APIResponseError):
        extractor.get_total_count(bad_response)


# ---------------------------------------------------------------------------
# test_parse_records — happy path
# ---------------------------------------------------------------------------

def test_parse_records_returns_correct_count(sample_nih_response):
    """parse_records should return one dict per result in the response."""
    extractor = make_extractor()
    records = extractor.parse_records(sample_nih_response)
    assert len(records) == 2


def test_parse_records_column_keys(sample_nih_response):
    """Every record must have exactly the 9 required output columns."""
    extractor = make_extractor()
    records = extractor.parse_records(sample_nih_response)
    expected_keys = {
        "FIRST", "LAST", "INSTITUTION", "TITLE",
        "FUNDING_AMT", "CURRENCY", "AWARD_DATE", "SOURCE", "LINK",
    }
    for record in records:
        assert set(record.keys()) == expected_keys


def test_parse_records_field_values(sample_nih_response):
    """Field values should be mapped correctly from the raw API response."""
    extractor = make_extractor()
    record = extractor.parse_records(sample_nih_response)[0]

    assert record["FIRST"] == "Jane"
    assert record["LAST"] == "Smith"
    assert record["INSTITUTION"] == "HARVARD UNIVERSITY"
    assert record["TITLE"] == "Study of Neural Plasticity"
    assert record["FUNDING_AMT"] == 500000
    assert record["CURRENCY"] == "USD"
    assert record["SOURCE"] == "NIH RePORTER"


def test_parse_records_strips_time_from_date(sample_nih_response):
    """Award date should be 'YYYY-MM-DD', not 'YYYY-MM-DDTHH:MM:SS'."""
    extractor = make_extractor()
    record = extractor.parse_records(sample_nih_response)[0]
    assert record["AWARD_DATE"] == "2025-01-10"
    assert "T" not in record["AWARD_DATE"]


def test_parse_records_link_format(sample_nih_response):
    """LINK must point to the NIH RePORTER project detail page."""
    extractor = make_extractor()
    record = extractor.parse_records(sample_nih_response)[0]
    assert record["LINK"] == "https://reporter.nih.gov/project-details/12345678"


# ---------------------------------------------------------------------------
# test_parse_records — missing / empty fields
# ---------------------------------------------------------------------------

def test_parse_records_missing_pi_uses_empty_string():
    """If principal_investigators list is empty, FIRST and LAST should be ''."""
    extractor = make_extractor()
    response = {
        "meta": {"total": 1},
        "results": [{
            "appl_id": 111,
            "project_title": "Test Grant",
            "award_amount": 100000,
            "award_notice_date": "2025-01-10T00:00:00",
            "principal_investigators": [],   # empty list
            "organization": {"org_name": "TEST UNIVERSITY"},
        }]
    }
    records = extractor.parse_records(response)
    assert records[0]["FIRST"] == ""
    assert records[0]["LAST"] == ""


def test_parse_records_missing_org_uses_empty_string():
    """If organization is missing, INSTITUTION should be ''."""
    extractor = make_extractor()
    response = {
        "meta": {"total": 1},
        "results": [{
            "appl_id": 222,
            "project_title": "Test Grant",
            "award_amount": 100000,
            "award_notice_date": "2025-01-10T00:00:00",
            "principal_investigators": [{"first_name": "A", "last_name": "B"}],
            # organization key is absent entirely
        }]
    }
    records = extractor.parse_records(response)
    assert records[0]["INSTITUTION"] == ""


def test_parse_records_skips_bad_record_continues():
    """
    A record that raises DataExtractionError should be skipped.
    The remaining valid records should still be returned.
    """
    extractor = make_extractor()

    # Patch _map_record to fail on first call, succeed on second
    good_record = {
        "FIRST": "Jane", "LAST": "Smith", "INSTITUTION": "MIT",
        "TITLE": "Good Grant", "FUNDING_AMT": 100000, "CURRENCY": "USD",
        "AWARD_DATE": "2025-01-10", "SOURCE": "NIH RePORTER",
        "LINK": "https://reporter.nih.gov/project-details/333",
    }

    call_count = {"n": 0}

    def fake_map(raw):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise DataExtractionError("Simulated bad record")
        return good_record

    extractor._map_record = fake_map

    response = {
        "meta": {"total": 2},
        "results": [{"appl_id": 1}, {"appl_id": 2}],
    }

    records = extractor.parse_records(response)

    # First record was skipped, second was kept
    assert len(records) == 1
    assert records[0]["FIRST"] == "Jane"


def test_parse_records_missing_results_key_raises():
    """parse_records must raise APIResponseError if 'results' key is absent."""
    extractor = make_extractor()
    with pytest.raises(APIResponseError):
        extractor.parse_records({"meta": {"total": 0}})


# ---------------------------------------------------------------------------
# test_empty_response
# ---------------------------------------------------------------------------

def test_empty_response_returns_empty_list(empty_nih_response):
    """parse_records on a zero-result response should return an empty list."""
    extractor = make_extractor()
    records = extractor.parse_records(empty_nih_response)
    assert records == []
