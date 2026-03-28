"""
NIH RePORTER Grant Extractor
-----------------------------
Fetches grant award records from the NIH RePORTER API (v2) for a given date.

API Reference: https://api.reporter.nih.gov/
Endpoint:      POST https://api.reporter.nih.gov/v2/projects/search
Auth required: No — public API

Output columns: FIRST, LAST, INSTITUTION, TITLE, FUNDING_AMT, CURRENCY,
                AWARD_DATE, SOURCE, LINK
"""

import requests

from exceptions import APIRequestError, APIResponseError, DataExtractionError
from extractors.base import BaseExtractor

# Base URL for the NIH RePORTER project search endpoint
NIH_API_URL = "https://api.reporter.nih.gov/v2/projects/search"

# Direct link to a project detail page on NIH RePORTER website
NIH_PROJECT_URL = "https://reporter.nih.gov/project-details/{appl_id}"

# Number of records to request per API call (max allowed: 500)
PAGE_SIZE = 500


class NIHExtractor(BaseExtractor):
    """
    Extracts grant award records from the NIH RePORTER API.

    Inherits the full pagination loop and Excel save logic from BaseExtractor.
    This class only defines:
      - How to build the API request (fetch_page)
      - How to map NIH fields to our output columns (parse_records)
      - Where to find total count and page size

    Usage:
        extractor = NIHExtractor(target_date=date(2024, 1, 15))
        output_file = extractor.run()
    """

    @property
    def source_name(self) -> str:
        """Short name used in the output filename: NIH_YYYYMMDD.xlsx"""
        return "NIH"

    def page_size(self) -> int:
        """Number of records per API page."""
        return PAGE_SIZE

    def get_total_count(self, response: dict) -> int:
        """
        Extract total available record count from the API response.

        NIH returns: { "meta": { "total": 1234 }, "results": [...] }

        Args:
            response: Raw dict from fetch_page().

        Returns:
            Total number of matching records.

        Raises:
            APIResponseError: If the expected key is missing from the response.
        """
        try:
            return response["meta"]["total"]
        except KeyError as e:
            raise APIResponseError(
                f"NIH response missing expected key: {e}. "
                f"Keys found: {list(response.keys())}"
            ) from e

    def fetch_page(self, offset: int) -> dict:
        """
        Send a POST request to the NIH API for one page of results.

        Filters by award_notice_date matching the target date.
        NIH uses POST with a JSON body — not a standard GET with params.

        Args:
            offset: Zero-based record offset (e.g. 0, 500, 1000...).

        Returns:
            Parsed JSON response as a dict.

        Raises:
            APIRequestError: On network failure or 5xx server error.
            APIResponseError: On 4xx error or unparseable response body.
        """
        # Format date as "MM/DD/YYYY" — the format NIH expects
        date_str = self.target_date.strftime("%m/%d/%Y")

        # Build the POST request body
        payload = {
            "criteria": {
                # Filter grants by the date the award notice was issued
                "award_notice_date": {
                    "from_date": date_str,
                    "to_date": date_str,
                }
            },
            "offset": offset,
            "limit": PAGE_SIZE,
            # Only request the fields we actually need — faster response
            "include_fields": [
                "ApplId",
                "ProjectTitle",
                "AwardAmount",
                "AwardNoticeDate",
                "PrincipalInvestigators",
                "Organization",
            ],
        }

        self.logger.debug(
            f"POST {NIH_API_URL} | offset={offset} | date={date_str}"
        )

        try:
            response = requests.post(NIH_API_URL, json=payload, timeout=30)
        except requests.exceptions.ConnectionError as e:
            raise APIRequestError(f"NIH: Connection failed: {e}") from e
        except requests.exceptions.Timeout as e:
            raise APIRequestError(f"NIH: Request timed out: {e}") from e
        except requests.exceptions.RequestException as e:
            raise APIRequestError(f"NIH: Unexpected request error: {e}") from e

        # Check HTTP status codes
        if response.status_code >= 500:
            raise APIRequestError(
                f"NIH: Server error {response.status_code}. "
                f"Response: {response.text[:200]}"
            )
        if response.status_code >= 400:
            raise APIResponseError(
                f"NIH: Client error {response.status_code}. "
                f"Response: {response.text[:200]}"
            )

        # Parse JSON body
        try:
            return response.json()
        except ValueError as e:
            raise APIResponseError(
                f"NIH: Failed to parse JSON response: {e}. "
                f"Raw response: {response.text[:300]}"
            ) from e

    def parse_records(self, response: dict) -> list[dict]:
        """
        Map NIH API response fields to our standard output columns.

        For each grant in the response, extract:
          - PI first and last name (from principal_investigators list)
          - Institution name
          - Grant title
          - Award amount (USD)
          - Award notice date
          - Direct link to the NIH project page

        If a single record is malformed, it is logged and skipped (DataExtractionError).
        The rest of the records on the page are still processed.

        Args:
            response: Raw dict from fetch_page().

        Returns:
            List of dicts with keys: FIRST, LAST, INSTITUTION, TITLE,
            FUNDING_AMT, CURRENCY, AWARD_DATE, SOURCE, LINK.

        Raises:
            APIResponseError: If the 'results' key is missing entirely.
        """
        try:
            raw_records = response["results"]
        except KeyError as e:
            raise APIResponseError(
                f"NIH: 'results' key missing from response. "
                f"Keys found: {list(response.keys())}"
            ) from e

        mapped = []

        for raw in raw_records:
            try:
                mapped.append(self._map_record(raw))
            except DataExtractionError as e:
                # Log and skip — one bad record should not stop the whole run
                self.logger.warning(f"NIH: Skipping record due to error: {e}")

        return mapped

    def _map_record(self, raw: dict) -> dict:
        """
        Map a single NIH grant record to our output column schema.

        NIH stores PI details in a list — we take the first PI only.
        If a field is absent, we use an empty string rather than crashing.

        Args:
            raw: A single project dict from the NIH API results list.

        Returns:
            Dict with keys matching OUTPUT_COLUMNS.

        Raises:
            DataExtractionError: If the record structure is too malformed to parse.
        """
        try:
            # Principal investigator — NIH can have multiple; we take the first
            pi_list = raw.get("principal_investigators", [])
            pi = pi_list[0] if pi_list else {}

            first_name = pi.get("first_name", "")
            last_name = pi.get("last_name", "")

            # Organisation
            org = raw.get("organization", {})
            institution = org.get("org_name", "")

            # Core fields
            title = raw.get("project_title", "")
            amount = raw.get("award_amount", "")
            award_date = raw.get("award_notice_date", "")

            # Strip trailing time component if present: "2024-01-15T00:00:00" → "2024-01-15"
            if award_date and "T" in award_date:
                award_date = award_date.split("T")[0]

            # Build direct URL to project page on NIH RePORTER website
            appl_id = raw.get("appl_id", "")
            link = NIH_PROJECT_URL.format(appl_id=appl_id) if appl_id else ""

            return {
                "FIRST": first_name,
                "LAST": last_name,
                "INSTITUTION": institution,
                "TITLE": title,
                "FUNDING_AMT": amount,
                "CURRENCY": "USD",
                "AWARD_DATE": award_date,
                "SOURCE": "NIH RePORTER",
                "LINK": link,
            }

        except Exception as e:
            raise DataExtractionError(
                f"NIH: Could not map record (appl_id={raw.get('appl_id', 'unknown')}): {e}"
            ) from e
