"""
NSF Awards Grant Extractor
---------------------------
Fetches grant award records from the NSF Awards API (v1) for a given date.

API Reference: https://resources.research.gov/common/webapi/awardapisearch-v1.htm
Endpoint:      GET https://api.nsf.gov/services/v1/awards.json
Auth required: No — public API

Key differences from NIH:
  - GET request with query params (NIH used POST with JSON body)
  - Max 25 records per page (NIH allowed 500)
  - Date filter uses dateStart/dateEnd in MM/DD/YYYY format
  - Total count lives in response.metadata.totalCount

Output columns: FIRST, LAST, INSTITUTION, TITLE, FUNDING_AMT, CURRENCY,
                AWARD_DATE, SOURCE, LINK
"""

from datetime import datetime

import requests

from exceptions import APIRequestError, APIResponseError, DataExtractionError
from extractors.base import BaseExtractor

# Base URL for the NSF Awards search endpoint — .json suffix sets response format
NSF_API_URL = "https://api.nsf.gov/services/v1/awards.json"

# Direct link to an award detail page on the NSF website
NSF_AWARD_URL = "https://www.nsf.gov/awardsearch/showAward?AWD_ID={award_id}"

# NSF allows max 25 records per page
PAGE_SIZE = 25


class NSFExtractor(BaseExtractor):
    """
    Extracts grant award records from the NSF Awards API.

    Inherits the full pagination loop and Excel save logic from BaseExtractor.
    This class only defines:
      - How to build the GET request (fetch_page)
      - How to map NSF fields to our output columns (parse_records)
      - Where to find total count and page size

    Usage:
        extractor = NSFExtractor(target_date=date(2025, 1, 10))
        output_file = extractor.run()
    """

    @property
    def source_name(self) -> str:
        """Short name used in the output filename: NSF_YYYYMMDD.xlsx"""
        return "NSF"

    def page_size(self) -> int:
        """Number of records per API page (NSF max is 25)."""
        return PAGE_SIZE

    def get_total_count(self, response: dict) -> int:
        """
        Extract total available record count from the NSF API response.

        NSF returns: { "response": { "metadata": { "totalCount": 9 }, "award": [...] } }

        Args:
            response: Raw dict from fetch_page().

        Returns:
            Total number of matching records.

        Raises:
            APIResponseError: If the expected keys are missing from the response.
        """
        try:
            return int(response["response"]["metadata"]["totalCount"])
        except (KeyError, TypeError, ValueError) as e:
            raise APIResponseError(
                f"NSF: Could not read totalCount from response: {e}. "
                f"Keys found: {list(response.keys())}"
            ) from e

    def fetch_page(self, offset: int) -> dict:
        """
        Send a GET request to the NSF API for one page of results.

        Filters by award date (date field) matching the target date.
        NSF uses a GET request with query parameters — no request body needed.

        Args:
            offset: Zero-based record offset (e.g. 0, 25, 50...).

        Returns:
            Parsed JSON response as a dict.

        Raises:
            APIRequestError: On network failure or 5xx server error.
            APIResponseError: On 4xx error or unparseable response body.
        """
        # NSF date filter format: MM/DD/YYYY
        date_str = self.target_date.strftime("%m/%d/%Y")

        params = {
            "dateStart": date_str,
            "dateEnd": date_str,
            "rpp": PAGE_SIZE,       # results per page
            "offset": offset,
            # Request only the fields we need — smaller response, faster transfer
            "printFields": (
                "id,title,piFirstName,piLastName,awardeeName,"
                "estimatedTotalAmt,date"
            ),
        }

        self.logger.debug(
            f"GET {NSF_API_URL} | offset={offset} | date={date_str}"
        )

        try:
            response = requests.get(NSF_API_URL, params=params, timeout=30)
        except requests.exceptions.ConnectionError as e:
            raise APIRequestError(f"NSF: Connection failed: {e}") from e
        except requests.exceptions.Timeout as e:
            raise APIRequestError(f"NSF: Request timed out: {e}") from e
        except requests.exceptions.RequestException as e:
            raise APIRequestError(f"NSF: Unexpected request error: {e}") from e

        # Check HTTP status codes
        if response.status_code >= 500:
            raise APIRequestError(
                f"NSF: Server error {response.status_code}. "
                f"Response: {response.text[:200]}"
            )
        if response.status_code >= 400:
            raise APIResponseError(
                f"NSF: Client error {response.status_code}. "
                f"Response: {response.text[:200]}"
            )

        # Parse JSON body
        try:
            return response.json()
        except ValueError as e:
            raise APIResponseError(
                f"NSF: Failed to parse JSON response: {e}. "
                f"Raw response: {response.text[:300]}"
            ) from e

    def parse_records(self, response: dict) -> list[dict]:
        """
        Map NSF API response fields to our standard output columns.

        For each award in the response, extract:
          - PI first and last name
          - Awardee institution name
          - Grant title
          - Estimated total amount (USD)
          - Award date
          - Direct link to the NSF award detail page

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
            raw_records = response["response"]["award"]
        except KeyError as e:
            raise APIResponseError(
                f"NSF: Expected key missing from response: {e}. "
                f"Keys found: {list(response.get('response', {}).keys())}"
            ) from e

        # NSF returns None for award key when there are zero results
        if not raw_records:
            return []

        mapped = []

        for raw in raw_records:
            try:
                mapped.append(self._map_record(raw))
            except DataExtractionError as e:
                # Log and skip — one bad record should not stop the whole run
                self.logger.warning(f"NSF: Skipping record due to error: {e}")

        return mapped

    def _map_record(self, raw: dict) -> dict:
        """
        Map a single NSF award record to our output column schema.

        NSF date format is MM/DD/YYYY — we normalise it to YYYY-MM-DD
        to match the rest of the pipeline.

        Args:
            raw: A single award dict from the NSF API results list.

        Returns:
            Dict with keys matching OUTPUT_COLUMNS.

        Raises:
            DataExtractionError: If the record is too malformed to parse.
        """
        try:
            award_id = raw.get("id", "")

            # Normalise date from MM/DD/YYYY → YYYY-MM-DD
            raw_date = raw.get("date", "")
            award_date = self._normalise_date(raw_date)

            return {
                "FIRST": raw.get("piFirstName", ""),
                "LAST": raw.get("piLastName", ""),
                "INSTITUTION": raw.get("awardeeName", ""),
                "TITLE": raw.get("title", ""),
                "FUNDING_AMT": raw.get("estimatedTotalAmt", ""),
                "CURRENCY": "USD",
                "AWARD_DATE": award_date,
                "SOURCE": "NSF Awards",
                "LINK": NSF_AWARD_URL.format(award_id=award_id) if award_id else "",
            }

        except Exception as e:
            raise DataExtractionError(
                f"NSF: Could not map record (id={raw.get('id', 'unknown')}): {e}"
            ) from e

    def _normalise_date(self, date_str: str) -> str:
        """
        Convert NSF date format MM/DD/YYYY to YYYY-MM-DD.

        Args:
            date_str: Date string from the NSF API, e.g. '01/10/2025'.

        Returns:
            Normalised date string 'YYYY-MM-DD', or original string if parsing fails.
        """
        if not date_str:
            return ""

        try:
            return datetime.strptime(date_str, "%m/%d/%Y").strftime("%Y-%m-%d")
        except ValueError:
            # Return as-is rather than crashing — log so we can investigate
            self.logger.warning(
                f"NSF: Unexpected date format '{date_str}' — storing as-is"
            )
            return date_str
