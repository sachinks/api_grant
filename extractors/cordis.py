"""
CORDIS EU Grant Extractor
--------------------------
Fetches EU research grant records from the CORDIS project search API.

API Reference: https://cordis.europa.eu/projects/en
Endpoint:      GET https://cordis.europa.eu/projects/api/search/json
Auth required: No — public search API used by the CORDIS website itself

Key differences from NIH/NSF:
  - Weekly cadence (not daily) — JD specifies up to 1,000 records per pull
  - PI first/last name not available in search results — CORDIS stores
    coordinator organisation only; FIRST and LAST will be left blank
  - Funding is in EUR (not USD)
  - Date filter uses Solr query syntax: contentUpdateDate>=[YYYY-MM-DD]
  - Pagination uses 1-based page numbers (not offset)

NOTE: CORDIS servers may be geo-restricted in some network environments.
      If requests time out, test from a different network or VPN to EU.

Output columns: FIRST, LAST, INSTITUTION, TITLE, FUNDING_AMT, CURRENCY,
                AWARD_DATE, SOURCE, LINK
"""

from datetime import timedelta

import requests

from exceptions import APIRequestError, APIResponseError, DataExtractionError
from extractors.base import BaseExtractor

# Search API used by the CORDIS website — no authentication required
CORDIS_API_URL = "https://cordis.europa.eu/projects/api/search/json"

# Direct link to a project detail page on the CORDIS website
CORDIS_PROJECT_URL = "https://cordis.europa.eu/project/id/{project_id}"

# Records per page — CORDIS search API supports up to 100
PAGE_SIZE = 100


class CORDISExtractor(BaseExtractor):
    """
    Extracts EU research grant records from the CORDIS project search API.

    Inherits the full pagination loop and Excel save logic from BaseExtractor.
    This class only defines:
      - How to build the GET request (fetch_page)
      - How to map CORDIS fields to our output columns (parse_records)
      - Where to find total count and page size

    Pagination note:
        CORDIS uses 1-based page numbers. BaseExtractor passes an offset
        (0, 100, 200...). We convert offset → page number inside fetch_page.

    Weekly cadence note:
        CORDIS is intended to be run weekly. The date range defaults to
        the 7 days prior to target_date rather than a single day.
        Use --date to override the end of the 7-day window.

    Usage:
        extractor = CORDISExtractor(target_date=date(2025, 1, 10))
        output_file = extractor.run()
    """

    @property
    def source_name(self) -> str:
        """Short name used in the output filename: CORDIS_YYYYMMDD.xlsx"""
        return "CORDIS"

    def page_size(self) -> int:
        """Number of records per API page."""
        return PAGE_SIZE

    def get_total_count(self, response: dict) -> int:
        """
        Extract total available record count from the CORDIS API response.

        CORDIS returns:
            { "data": { "projects": { "project": [...], "totalCount": 123 } } }

        Args:
            response: Raw dict from fetch_page().

        Returns:
            Total number of matching records.

        Raises:
            APIResponseError: If expected keys are missing from the response.
        """
        try:
            return int(response["data"]["projects"]["totalCount"])
        except (KeyError, TypeError, ValueError) as e:
            raise APIResponseError(
                f"CORDIS: Could not read totalCount from response: {e}. "
                f"Top-level keys found: {list(response.keys())}"
            ) from e

    def fetch_page(self, offset: int) -> dict:
        """
        Send a GET request to the CORDIS API for one page of results.

        Filters by contentUpdateDate within the last 7 days ending on target_date.
        CORDIS uses 1-based page numbers — we convert from BaseExtractor's offset.

        Args:
            offset: Zero-based record offset from BaseExtractor pagination loop.
                    Converted to a 1-based page number internally.

        Returns:
            Parsed JSON response as a dict.

        Raises:
            APIRequestError: On network failure, timeout, or 5xx server error.
            APIResponseError: On 4xx error or unparseable response body.
        """
        # Convert offset → 1-based page number
        page = (offset // PAGE_SIZE) + 1

        # Weekly window: pull records updated in the 7 days up to target_date
        date_from = self.target_date - timedelta(days=7)
        date_to = self.target_date

        # Solr-style query: contentUpdateDate range filter
        query = (
            f"contentUpdateDate>={date_from.strftime('%Y-%m-%d')} "
            f"AND contentUpdateDate<={date_to.strftime('%Y-%m-%d')}"
        )

        params = {
            "q": query,
            "p": page,
            "num": PAGE_SIZE,
            # Sort by update date descending — most recent first
            "srt": "contentUpdateDate:decreasing",
        }

        self.logger.debug(
            f"GET {CORDIS_API_URL} | page={page} | "
            f"dates={date_from} to {date_to}"
        )

        try:
            response = requests.get(CORDIS_API_URL, params=params, timeout=60)
        except requests.exceptions.ConnectionError as e:
            raise APIRequestError(
                f"CORDIS: Connection failed — server may be geo-restricted: {e}"
            ) from e
        except requests.exceptions.Timeout as e:
            raise APIRequestError(
                f"CORDIS: Request timed out after 60s — "
                f"server may be slow or unreachable: {e}"
            ) from e
        except requests.exceptions.RequestException as e:
            raise APIRequestError(f"CORDIS: Unexpected request error: {e}") from e

        # Check HTTP status codes
        if response.status_code >= 500:
            raise APIRequestError(
                f"CORDIS: Server error {response.status_code}. "
                f"Response: {response.text[:200]}"
            )
        if response.status_code >= 400:
            raise APIResponseError(
                f"CORDIS: Client error {response.status_code}. "
                f"Response: {response.text[:200]}"
            )

        # Parse JSON body
        try:
            return response.json()
        except ValueError as e:
            raise APIResponseError(
                f"CORDIS: Failed to parse JSON response: {e}. "
                f"Raw response: {response.text[:300]}"
            ) from e

    def parse_records(self, response: dict) -> list[dict]:
        """
        Map CORDIS API response fields to our standard output columns.

        CORDIS does not expose individual PI names in the search endpoint.
        FIRST and LAST will be empty strings — the coordinator organisation
        name is mapped to INSTITUTION instead.

        If a single record is malformed, it is logged and skipped.
        The rest of the records on the page are still processed.

        Args:
            response: Raw dict from fetch_page().

        Returns:
            List of dicts with keys matching OUTPUT_COLUMNS.

        Raises:
            APIResponseError: If the expected response structure is missing.
        """
        try:
            raw_records = response["data"]["projects"]["project"]
        except KeyError as e:
            raise APIResponseError(
                f"CORDIS: Expected key missing from response: {e}. "
                f"Top-level keys: {list(response.keys())}"
            ) from e

        if not raw_records:
            return []

        # API may return a single dict instead of a list when there's only 1 result
        if isinstance(raw_records, dict):
            raw_records = [raw_records]

        mapped = []

        for raw in raw_records:
            try:
                mapped.append(self._map_record(raw))
            except DataExtractionError as e:
                self.logger.warning(f"CORDIS: Skipping record due to error: {e}")

        return mapped

    def _map_record(self, raw: dict) -> dict:
        """
        Map a single CORDIS project record to our output column schema.

        CORDIS funding fields:
          - ecMaxContribution: EU contribution only
          - totalCost: total project cost (includes non-EU funding)
        We use ecMaxContribution as FUNDING_AMT (the grant award from EU).

        Coordinator organisation is extracted from the relations block.
        If no coordinator is found, INSTITUTION is left empty.

        Args:
            raw: A single project dict from the CORDIS API results list.

        Returns:
            Dict with keys matching OUTPUT_COLUMNS.

        Raises:
            DataExtractionError: If the record is too malformed to parse.
        """
        try:
            project_id = raw.get("id", "")

            # Extract coordinator organisation from the relations block
            institution = self._extract_coordinator(raw)

            # Use ecMaxContribution (EU grant amount) as the funding figure
            funding_amt = raw.get("ecMaxContribution", raw.get("totalCost", ""))

            # Use startDate as the award date — contentUpdateDate is update time
            award_date = raw.get("startDate", "")

            return {
                "FIRST": "",   # Not available in CORDIS search results
                "LAST": "",    # Not available in CORDIS search results
                "INSTITUTION": institution,
                "TITLE": raw.get("title", ""),
                "FUNDING_AMT": funding_amt,
                "CURRENCY": "EUR",
                "AWARD_DATE": award_date,
                "SOURCE": "CORDIS",
                "LINK": CORDIS_PROJECT_URL.format(project_id=project_id) if project_id else "",
            }

        except Exception as e:
            raise DataExtractionError(
                f"CORDIS: Could not map record (id={raw.get('id', 'unknown')}): {e}"
            ) from e

    def _extract_coordinator(self, raw: dict) -> str:
        """
        Extract the name of the coordinator organisation from a CORDIS record.

        CORDIS stores organisations in a nested relations block. We look for
        the organisation with role='coordinator'. If none is found, we return
        the first organisation name available, or an empty string.

        Args:
            raw: A single project dict from the CORDIS API results list.

        Returns:
            Coordinator organisation name, or '' if not found.
        """
        try:
            relations = raw.get("relations", {})
            associations = relations.get("associations", {})
            orgs = associations.get("organization", [])

            # API may return a single dict instead of a list for one organisation
            if isinstance(orgs, dict):
                orgs = [orgs]

            if not orgs:
                return ""

            # Prefer the coordinator role
            for org in orgs:
                if str(org.get("role", "")).lower() == "coordinator":
                    return org.get("name", "")

            # Fall back to first organisation if no coordinator role found
            return orgs[0].get("name", "")

        except Exception:
            # Non-fatal — return empty rather than crashing the record
            return ""
