"""
UKRI Gateway Grant Extractor
------------------------------
Fetches research grant records from the UKRI Gateway to Research (GTR) API.

API Reference: https://gtr.ukri.org/resources/GtR-2-API-v1.7.5.pdf
Endpoint:      GET https://gtr.ukri.org/gtr/api/projects
Auth required: No — public API

Key differences from NIH/NSF/CORDIS:
  - No server-side date filter — UKRI API only supports sorting, not filtering
    by date. We sort by start date descending and filter client-side using
    the 'created' epoch millisecond timestamp on each record.
  - Linked resource model — PI name, institution, and funding amount are NOT
    in the project response. Each requires a secondary GET to a linked URL.
  - 1-based page numbers (not offset-based like NIH/NSF)
  - GBP currency
  - Overrides BaseExtractor.run() with its own scanning loop because
    we cannot know upfront how many records match target_date.

Limitation:
    UKRI does not expose a 'created date' sort field. We scan up to
    MAX_SCAN_PAGES pages (default 50 = 5,000 records) and stop early
    when no matching records are found on a page. Records added on
    target_date but with very old start dates may be missed.
    This is a documented API limitation, not a bug.

Output columns: FIRST, LAST, INSTITUTION, TITLE, FUNDING_AMT, CURRENCY,
                AWARD_DATE, SOURCE, LINK
"""

from datetime import datetime, timezone

import requests

from exceptions import APIRequestError, APIResponseError, DataExtractionError
from extractors.base import BaseExtractor
from utils.timeit import timeit

# Base URL for the UKRI GTR API
UKRI_API_URL = "https://gtr.ukri.org/gtr/api/projects"

# Direct link to a project page on the UKRI Gateway website
UKRI_PROJECT_URL = "https://gtr.ukri.org/projects?ref={ref}"

# JSON content type header required by UKRI API
UKRI_HEADERS = {"Accept": "application/vnd.rcuk.gtr.json-v7"}

# Records per page — UKRI allows 10-100
PAGE_SIZE = 100

# Maximum pages to scan per run — prevents scanning all 17k+ pages.
# 50 pages × 100 records = 5,000 records scanned maximum.
MAX_SCAN_PAGES = 50

# Maximum matching records to enrich per run — each match triggers 3 secondary
# API calls (org, PI, fund). Caps total secondary requests at 3 × MAX_RECORDS.
# For normal daily use, well under 500 new records are added per day.
MAX_RECORDS = 500


class UKRIExtractor(BaseExtractor):
    """
    Extracts research grant records from the UKRI Gateway to Research API.

    Because UKRI does not support server-side date filtering, this extractor
    overrides BaseExtractor.run() with its own scanning loop that:
      1. Fetches pages sorted by start date descending (most recent first)
      2. Filters each record by its 'created' epoch timestamp
      3. Stops early when no records on a page match the target date
      4. Caps at MAX_SCAN_PAGES to prevent unbounded scanning

    For each matching project, secondary GET calls are made to fetch:
      - Lead organisation name (INSTITUTION)
      - Principal investigator name (FIRST, LAST)
      - Fund value in GBP (FUNDING_AMT)

    Usage:
        extractor = UKRIExtractor(target_date=date(2025, 1, 10))
        output_file = extractor.run()
    """

    @property
    def source_name(self) -> str:
        """Short name used in the output filename: UKRI_YYYYMMDD.xlsx"""
        return "UKRI"

    def page_size(self) -> int:
        """Number of records per API page."""
        return PAGE_SIZE

    def get_total_count(self, response: dict) -> int:
        """
        Extract total record count from UKRI API response.

        UKRI returns: { "totalSize": 173200, "project": [...] }

        Args:
            response: Raw dict from fetch_page().

        Returns:
            Total number of records in the database (not filtered by date).

        Raises:
            APIResponseError: If the expected key is missing.
        """
        try:
            return int(response["totalSize"])
        except (KeyError, TypeError, ValueError) as e:
            raise APIResponseError(
                f"UKRI: Could not read totalSize from response: {e}. "
                f"Keys found: {list(response.keys())}"
            ) from e

    def fetch_page(self, offset: int) -> dict:
        """
        Send a GET request to the UKRI API for one page of results.

        Sorted by start date descending — most recently started projects first.
        UKRI uses 1-based page numbers, converted from BaseExtractor offset.

        Args:
            offset: Zero-based offset from pagination loop.
                    Converted to 1-based page number internally.

        Returns:
            Parsed JSON response as a dict.

        Raises:
            APIRequestError: On network failure or 5xx server error.
            APIResponseError: On 4xx error or unparseable response.
        """
        page = (offset // PAGE_SIZE) + 1

        params = {
            "p": page,
            "s": PAGE_SIZE,
            "sf": "pro.sd",   # sort by start date
            "so": "D",        # descending — most recent first
        }

        self.logger.debug(f"GET {UKRI_API_URL} | page={page}")

        try:
            response = requests.get(
                UKRI_API_URL, params=params, headers=UKRI_HEADERS, timeout=30
            )
        except requests.exceptions.ConnectionError as e:
            raise APIRequestError(f"UKRI: Connection failed: {e}") from e
        except requests.exceptions.Timeout as e:
            raise APIRequestError(f"UKRI: Request timed out: {e}") from e
        except requests.exceptions.RequestException as e:
            raise APIRequestError(f"UKRI: Unexpected request error: {e}") from e

        if response.status_code >= 500:
            raise APIRequestError(
                f"UKRI: Server error {response.status_code}. "
                f"Response: {response.text[:200]}"
            )
        if response.status_code >= 400:
            raise APIResponseError(
                f"UKRI: Client error {response.status_code}. "
                f"Response: {response.text[:200]}"
            )

        try:
            return response.json()
        except ValueError as e:
            raise APIResponseError(
                f"UKRI: Failed to parse JSON response: {e}. "
                f"Raw response: {response.text[:300]}"
            ) from e

    def parse_records(self, response: dict) -> list[dict]:
        """
        Filter and map UKRI records for target_date using 'created' timestamp.

        UKRI stores record creation time as epoch milliseconds in the 'created'
        field. We convert this to a date and compare against self.target_date.

        For each matching project, secondary GET calls fetch the linked
        organisation, PI, and fund details.

        Args:
            response: Raw dict from fetch_page().

        Returns:
            List of dicts with keys matching OUTPUT_COLUMNS.
            Empty list if no records on this page match target_date.

        Raises:
            APIResponseError: If the 'project' key is missing from the response.
        """
        try:
            raw_records = response.get("project", [])
        except (KeyError, TypeError) as e:
            raise APIResponseError(
                f"UKRI: Could not read project list from response: {e}"
            ) from e

        if not raw_records:
            return []

        mapped = []

        for raw in raw_records:
            try:
                # Check if this record was created on target_date
                created_ms = raw.get("created")
                if not self._is_target_date(created_ms):
                    continue

                mapped.append(self._map_record(raw))

            except DataExtractionError as e:
                self.logger.warning(f"UKRI: Skipping record due to error: {e}")

        return mapped

    @timeit
    def run(self) -> str:
        """
        Scan pages, collect records matching target_date, save to Excel.

        Overrides BaseExtractor.run() because UKRI requires client-side date
        filtering and cannot benefit from total_count-based pagination stopping.

        Stops early when:
          - A full page has no matching records (records are getting old)
          - MAX_SCAN_PAGES pages have been scanned

        Returns:
            Path to the saved .xlsx file.
        """
        from utils.excel import save_to_excel

        all_records = []
        page = 1
        consecutive_empty = 0

        self.logger.info(
            f"Starting UKRI scan for target_date={self.target_date} "
            f"(max {MAX_SCAN_PAGES} pages)"
        )

        while page <= MAX_SCAN_PAGES:
            offset = (page - 1) * PAGE_SIZE
            self.logger.debug(f"Scanning page {page}/{MAX_SCAN_PAGES}")

            response = self._fetch_with_retry(offset)
            records = self.parse_records(response)

            if records:
                all_records.extend(records)
                consecutive_empty = 0

                # Safety cap — stop if we've collected unexpectedly many records.
                # Prevents runaway secondary API calls on bulk-import days.
                if len(all_records) >= MAX_RECORDS:
                    self.logger.warning(
                        f"Reached MAX_RECORDS limit ({MAX_RECORDS}) — stopping. "
                        f"Check if a bulk import occurred on {self.target_date}."
                    )
                    break
            else:
                consecutive_empty += 1
                # Stop early after 3 consecutive empty pages — records
                # are sorted by start date, and we're moving away from target_date
                if consecutive_empty >= 3:
                    self.logger.info(
                        f"3 consecutive empty pages — stopping early at page {page}"
                    )
                    break

            # Stop if we've reached the last page of results
            total_pages = response.get("totalPages", 0)
            if page >= total_pages:
                break

            page += 1

        self.logger.info(f"Collected {len(all_records)} records for {self.target_date}")

        filename = f"{self.source_name}_{self.target_date.strftime('%Y%m%d')}.xlsx"
        save_to_excel(all_records, filename)
        self.logger.info(f"Saved: {filename}")

        return filename

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _is_target_date(self, created_ms: int | None) -> bool:
        """
        Check if an epoch millisecond timestamp falls on self.target_date (UTC).

        Args:
            created_ms: Epoch timestamp in milliseconds, or None.

        Returns:
            True if the timestamp's UTC date matches self.target_date.
        """
        if created_ms is None:
            return False

        try:
            created_date = datetime.fromtimestamp(
                created_ms / 1000, tz=timezone.utc
            ).date()
            return created_date == self.target_date
        except (OSError, ValueError, TypeError):
            return False

    def _map_record(self, raw: dict) -> dict:
        """
        Map a single UKRI project record to our output column schema.

        Makes secondary API calls to linked resources for:
          - Lead organisation name (INSTITUTION)
          - Principal investigator (FIRST, LAST)
          - Fund value in GBP (FUNDING_AMT)

        Args:
            raw: A single project dict from the UKRI API results list.

        Returns:
            Dict with keys matching OUTPUT_COLUMNS.

        Raises:
            DataExtractionError: If the record is too malformed to parse.
        """
        try:
            title = raw.get("title", "")

            # Extract RCUK reference number for the project URL
            ref = self._extract_ref(raw)
            link = UKRI_PROJECT_URL.format(ref=ref) if ref else ""

            # Extract linked resource URLs from the links block
            links = self._extract_links(raw)

            # Fetch secondary resources — all fail gracefully with empty strings
            institution = self._fetch_org_name(links.get("LEAD_ORG", ""))
            first, last = self._fetch_pi_name(links.get("PI_PER", ""))
            funding_amt, award_date = self._fetch_fund_details(links.get("FUND", ""))

            return {
                "FIRST": first,
                "LAST": last,
                "INSTITUTION": institution,
                "TITLE": title,
                "FUNDING_AMT": funding_amt,
                "CURRENCY": "GBP",
                "AWARD_DATE": award_date,
                "SOURCE": "UKRI Gateway",
                "LINK": link,
            }

        except Exception as e:
            raise DataExtractionError(
                f"UKRI: Could not map record (id={raw.get('id', 'unknown')}): {e}"
            ) from e

    def _extract_links(self, raw: dict) -> dict:
        """
        Extract named linked resource URLs from a project's links block.

        UKRI stores relations as a list of link objects, each with 'rel' and
        'href'. We build a dict keyed by relation type for easy lookup.
        If multiple links share the same rel (e.g. multiple PI_PER), we take
        the first one only.

        Args:
            raw: A single project dict.

        Returns:
            Dict mapping relation type → href URL.
            e.g. { "LEAD_ORG": "http://...", "PI_PER": "http://...", "FUND": "http://..." }
        """
        result = {}
        try:
            link_list = raw.get("links", {}).get("link", [])
            if isinstance(link_list, dict):
                link_list = [link_list]
            for link in link_list:
                rel = link.get("rel", "")
                href = link.get("href", "")
                if rel and href and rel not in result:
                    result[rel] = href
        except Exception:
            pass  # Return empty dict — all enrichments will fall back gracefully
        return result

    def _extract_ref(self, raw: dict) -> str:
        """
        Extract the RCUK reference number from project identifiers.

        The RCUK reference is used to build the project URL on gtr.ukri.org.

        Args:
            raw: A single project dict.

        Returns:
            RCUK reference string, or '' if not found.
        """
        try:
            identifiers = raw.get("identifiers", {}).get("identifier", [])
            if isinstance(identifiers, dict):
                identifiers = [identifiers]
            for identifier in identifiers:
                if identifier.get("type") == "RCUK":
                    return identifier.get("value", "")
        except Exception:
            pass
        return ""

    def _fetch_resource(self, url: str) -> dict:
        """
        Fetch a linked UKRI resource URL and return parsed JSON.

        Args:
            url: Full UKRI API URL for the linked resource.

        Returns:
            Parsed JSON dict, or empty dict on any failure.
        """
        if not url:
            return {}
        try:
            response = requests.get(url, headers=UKRI_HEADERS, timeout=15)
            if response.status_code == 200:
                return response.json()
        except Exception:
            pass
        return {}

    def _fetch_org_name(self, url: str) -> str:
        """
        Fetch the organisation name from a UKRI organisation URL.

        Args:
            url: UKRI API URL for an organisation resource.

        Returns:
            Organisation name string, or '' if unavailable.
        """
        data = self._fetch_resource(url)
        return data.get("name", "")

    def _fetch_pi_name(self, url: str) -> tuple[str, str]:
        """
        Fetch the PI first and last name from a UKRI person URL.

        Args:
            url: UKRI API URL for a person resource.

        Returns:
            Tuple of (first_name, last_name). Both '' if unavailable.
        """
        data = self._fetch_resource(url)
        return data.get("firstName", ""), data.get("surname", "")

    def _fetch_fund_details(self, url: str) -> tuple[str, str]:
        """
        Fetch funding amount and start date from a UKRI fund URL.

        Fund response: { "valuePounds": { "amount": 150000, "currencyCode": "GBP" },
                         "start": 1674000000000 }

        Args:
            url: UKRI API URL for a fund resource.

        Returns:
            Tuple of (amount_str, award_date_str).
            amount_str: Fund amount as string, or '' if unavailable.
            award_date_str: Fund start date as 'YYYY-MM-DD', or '' if unavailable.
        """
        data = self._fetch_resource(url)

        amount = ""
        award_date = ""

        try:
            amount = str(data.get("valuePounds", {}).get("amount", ""))
        except Exception:
            pass

        try:
            start_ms = data.get("start")
            if start_ms:
                award_date = datetime.fromtimestamp(
                    start_ms / 1000, tz=timezone.utc
                ).strftime("%Y-%m-%d")
        except Exception:
            pass

        return amount, award_date
