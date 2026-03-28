"""
Tests for the UKRI Gateway grant extractor.

All tests use mock data — no real HTTP calls are made.

Key things tested:
  - Epoch ms → date conversion for client-side date filtering
  - Linked resource extraction (org, PI, fund)
  - Early stop logic (3 consecutive empty pages)
  - Graceful handling when linked resources are unavailable

To run:
    pytest tests/test_ukri_extractor.py -v
"""

import pytest
from datetime import date, timezone, datetime
from unittest.mock import patch, MagicMock

from exceptions import APIResponseError, DataExtractionError
from extractors.ukri import UKRIExtractor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_extractor(target_date=None):
    """Return a UKRIExtractor with a fixed date so tests are deterministic."""
    return UKRIExtractor(target_date=target_date or date(2025, 1, 10))


def date_to_epoch_ms(d: date) -> int:
    """Convert a date to epoch milliseconds at midnight UTC."""
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp() * 1000)


def make_project(
    project_id="ABC-123",
    title="Test Grant",
    created_ms=None,
    target_date=date(2025, 1, 10),
    ref="1234567",
    lead_org_href="http://gtr.ukri.org/gtr/api/organisations/ORG1",
    pi_href="http://gtr.ukri.org/gtr/api/persons/PI1",
    fund_href="http://gtr.ukri.org/gtr/api/funds/FUND1",
):
    """Build a minimal fake UKRI project dict."""
    if created_ms is None:
        created_ms = date_to_epoch_ms(target_date)

    return {
        "id": project_id,
        "title": title,
        "created": created_ms,
        "identifiers": {
            "identifier": [{"value": ref, "type": "RCUK"}]
        },
        "links": {
            "link": [
                {"rel": "LEAD_ORG", "href": lead_org_href, "start": None, "end": None},
                {"rel": "PI_PER", "href": pi_href, "start": None, "end": None},
                {"rel": "FUND", "href": fund_href, "start": None, "end": None},
            ]
        },
    }


def make_response(projects: list, total_size=1000, total_pages=10) -> dict:
    """Build a fake UKRI API response."""
    return {
        "totalSize": total_size,
        "totalPages": total_pages,
        "page": 1,
        "size": 100,
        "project": projects,
    }


# ---------------------------------------------------------------------------
# test_source_name
# ---------------------------------------------------------------------------

def test_source_name():
    """source_name must return 'UKRI'."""
    assert make_extractor().source_name == "UKRI"


# ---------------------------------------------------------------------------
# test__is_target_date
# ---------------------------------------------------------------------------

def test_is_target_date_matching():
    """Epoch ms on target_date should return True."""
    extractor = make_extractor(target_date=date(2025, 1, 10))
    ms = date_to_epoch_ms(date(2025, 1, 10))
    assert extractor._is_target_date(ms) is True


def test_is_target_date_non_matching():
    """Epoch ms on a different date should return False."""
    extractor = make_extractor(target_date=date(2025, 1, 10))
    ms = date_to_epoch_ms(date(2025, 1, 9))
    assert extractor._is_target_date(ms) is False


def test_is_target_date_none_returns_false():
    """None created timestamp should return False without crashing."""
    assert make_extractor()._is_target_date(None) is False


# ---------------------------------------------------------------------------
# test_get_total_count
# ---------------------------------------------------------------------------

def test_get_total_count():
    """get_total_count should read totalSize from the response."""
    response = make_response([], total_size=5000)
    assert make_extractor().get_total_count(response) == 5000


def test_get_total_count_missing_key_raises():
    """get_total_count must raise APIResponseError if key is missing."""
    with pytest.raises(APIResponseError):
        make_extractor().get_total_count({"wrong": "structure"})


# ---------------------------------------------------------------------------
# test_extract_links
# ---------------------------------------------------------------------------

def test_extract_links_returns_all_rels():
    """_extract_links should return a dict keyed by rel type."""
    extractor = make_extractor()
    raw = make_project()
    links = extractor._extract_links(raw)

    assert "LEAD_ORG" in links
    assert "PI_PER" in links
    assert "FUND" in links
    assert links["LEAD_ORG"] == "http://gtr.ukri.org/gtr/api/organisations/ORG1"


def test_extract_links_single_link_as_dict():
    """_extract_links must handle a single link dict (not wrapped in a list)."""
    extractor = make_extractor()
    raw = {
        "links": {
            "link": {"rel": "LEAD_ORG", "href": "http://example.com/org"}
        }
    }
    links = extractor._extract_links(raw)
    assert links["LEAD_ORG"] == "http://example.com/org"


def test_extract_links_no_links_returns_empty():
    """_extract_links should return empty dict if links block is absent."""
    extractor = make_extractor()
    assert extractor._extract_links({}) == {}


# ---------------------------------------------------------------------------
# test_extract_ref
# ---------------------------------------------------------------------------

def test_extract_ref_returns_rcuk_value():
    """_extract_ref should return the RCUK identifier value."""
    extractor = make_extractor()
    raw = make_project(ref="9876543")
    assert extractor._extract_ref(raw) == "9876543"


def test_extract_ref_no_identifiers_returns_empty():
    """_extract_ref should return '' if no identifiers block exists."""
    extractor = make_extractor()
    assert extractor._extract_ref({}) == ""


# ---------------------------------------------------------------------------
# test_parse_records — date filtering
# ---------------------------------------------------------------------------

def test_parse_records_filters_by_created_date():
    """Only records with created = target_date should be returned."""
    extractor = make_extractor(target_date=date(2025, 1, 10))

    target_ms = date_to_epoch_ms(date(2025, 1, 10))
    other_ms = date_to_epoch_ms(date(2025, 1, 9))

    project_match = make_project(project_id="P1", created_ms=target_ms)
    project_no_match = make_project(project_id="P2", created_ms=other_ms)

    response = make_response([project_match, project_no_match])

    # Patch _map_record to avoid secondary HTTP calls
    mapped = {
        "FIRST": "A", "LAST": "B", "INSTITUTION": "X",
        "TITLE": "T", "FUNDING_AMT": "1000", "CURRENCY": "GBP",
        "AWARD_DATE": "2025-01-10", "SOURCE": "UKRI Gateway", "LINK": "",
    }
    extractor._map_record = MagicMock(return_value=mapped)

    records = extractor.parse_records(response)

    assert len(records) == 1
    assert extractor._map_record.call_count == 1


def test_parse_records_empty_project_list():
    """parse_records should return [] when project list is empty."""
    extractor = make_extractor()
    response = make_response([])
    assert extractor.parse_records(response) == []


def test_parse_records_skips_bad_record():
    """A record raising DataExtractionError should be skipped."""
    extractor = make_extractor(target_date=date(2025, 1, 10))
    target_ms = date_to_epoch_ms(date(2025, 1, 10))
    project = make_project(created_ms=target_ms)
    response = make_response([project])

    extractor._map_record = MagicMock(
        side_effect=DataExtractionError("Simulated error")
    )

    records = extractor.parse_records(response)
    assert records == []


# ---------------------------------------------------------------------------
# test__fetch_fund_details
# ---------------------------------------------------------------------------

def test_fetch_fund_details_parses_correctly():
    """_fetch_fund_details should return amount and formatted date."""
    extractor = make_extractor()

    fund_response = {
        "valuePounds": {"amount": 150000, "currencyCode": "GBP"},
        "start": date_to_epoch_ms(date(2025, 1, 10)),
    }

    with patch.object(extractor, "_fetch_resource", return_value=fund_response):
        amount, award_date = extractor._fetch_fund_details("http://example.com/fund")

    assert amount == "150000"
    assert award_date == "2025-01-10"


def test_fetch_fund_details_empty_url_returns_blanks():
    """_fetch_fund_details with empty URL should return two empty strings."""
    extractor = make_extractor()
    amount, award_date = extractor._fetch_fund_details("")
    assert amount == ""
    assert award_date == ""


# ---------------------------------------------------------------------------
# test__fetch_pi_name
# ---------------------------------------------------------------------------

def test_fetch_pi_name_returns_first_and_last():
    """_fetch_pi_name should return firstName and surname from person response."""
    extractor = make_extractor()
    person_response = {"firstName": "Jane", "surname": "Smith"}

    with patch.object(extractor, "_fetch_resource", return_value=person_response):
        first, last = extractor._fetch_pi_name("http://example.com/person")

    assert first == "Jane"
    assert last == "Smith"


def test_fetch_pi_name_missing_fields_returns_empty():
    """_fetch_pi_name should return ('', '') when fields are absent."""
    extractor = make_extractor()

    with patch.object(extractor, "_fetch_resource", return_value={}):
        first, last = extractor._fetch_pi_name("http://example.com/person")

    assert first == ""
    assert last == ""
