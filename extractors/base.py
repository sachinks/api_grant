import logging
from abc import ABC, abstractmethod
from datetime import date, timedelta

import requests

from exceptions import APIRequestError, APIResponseError
from utils.excel import save_to_excel
from utils.retry import retry
from utils.timeit import timeit


class BaseExtractor(ABC):
    """
    Abstract base class for all grant API extractors.

    Every source (NIH, NSF, CORDIS, UKRI) extends this class and only
    needs to implement three methods:
        - fetch_page()   — hit the API for one page of results
        - parse_records() — map raw API response to our output columns
        - source_name()  — return the short name used in the filename

    Everything else — date handling, pagination loop, Excel save,
    logging, retries — is handled here once for all four scripts.
    """

    # Subclasses can override these defaults
    retries: int = 3
    delay: float = 2.0  # seconds between retries (multiplied per attempt)

    def __init__(self, target_date: date | None = None):
        self.logger = logging.getLogger(self.__class__.__name__)

        # Default to yesterday if no date provided (daily cadence)
        self.target_date: date = target_date or date.today() - timedelta(days=1)
        self.logger.info(f"Target date: {self.target_date}")

    # ------------------------------------------------------------------
    # Abstract interface — each source must implement these
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Short uppercase name for this source, e.g. 'NIH', 'NSF'."""
        ...

    @abstractmethod
    def fetch_page(self, offset: int) -> dict:
        """
        Fetch a single page of results from the API.

        Args:
            offset: Zero-based record offset for pagination.

        Returns:
            Raw API response as a dict.

        Raises:
            APIRequestError: On network errors or 5xx responses.
            APIResponseError: On unexpected response format.
        """
        ...

    @abstractmethod
    def parse_records(self, response: dict) -> list[dict]:
        """
        Extract and map records from one page of API response.

        Args:
            response: Raw dict returned by fetch_page().

        Returns:
            List of dicts, each with keys matching OUTPUT_COLUMNS.
            Return [] if no records found on this page.
        """
        ...

    @abstractmethod
    def get_total_count(self, response: dict) -> int:
        """
        Return the total number of records available (from first response).
        Used to know when pagination is complete.
        """
        ...

    @abstractmethod
    def page_size(self) -> int:
        """Number of records per page for this API."""
        ...

    # ------------------------------------------------------------------
    # Pagination engine — runs for all sources
    # ------------------------------------------------------------------

    @timeit
    def run(self) -> str:
        """
        Fetch all pages, collect all records, save to Excel.

        Returns:
            Path to the saved .xlsx file.
        """
        all_records = []
        offset = 0

        self.logger.info(f"Starting extraction from {self.source_name}")

        # Fetch first page to get total count
        first_response = self._fetch_with_retry(offset)
        total = self.get_total_count(first_response)
        self.logger.info(f"Total records available: {total}")

        if total == 0:
            self.logger.warning("No records found for this date range.")
        else:
            records = self.parse_records(first_response)
            all_records.extend(records)
            offset += self.page_size()

            # Fetch remaining pages
            while offset < total:
                self.logger.debug(f"Fetching offset {offset}/{total}")
                response = self._fetch_with_retry(offset)
                records = self.parse_records(response)

                if not records:
                    self.logger.warning(f"Empty page at offset {offset}, stopping.")
                    break

                all_records.extend(records)
                offset += self.page_size()

        self.logger.info(f"Collected {len(all_records)} records total")

        # Save to Excel
        filename = f"{self.source_name}_{self.target_date.strftime('%Y%m%d')}.xlsx"
        save_to_excel(all_records, filename)
        self.logger.info(f"Saved: {filename}")

        return filename

    @retry
    def _fetch_with_retry(self, offset: int) -> dict:
        """Wraps fetch_page() with the retry decorator."""
        return self.fetch_page(offset)

    # ------------------------------------------------------------------
    # Shared HTTP helper
    # ------------------------------------------------------------------

    def get(self, url: str, params: dict | None = None, timeout: int = 30) -> requests.Response:
        """
        Make a GET request with consistent error handling.

        Raises:
            APIRequestError: On connection errors or 5xx status codes.
            APIResponseError: On 4xx status codes.
        """
        try:
            response = requests.get(url, params=params, timeout=timeout)
        except requests.exceptions.RequestException as e:
            raise APIRequestError(f"Request failed: {e}") from e

        if response.status_code >= 500:
            raise APIRequestError(
                f"Server error {response.status_code} from {url}"
            )

        if response.status_code >= 400:
            raise APIResponseError(
                f"Client error {response.status_code} from {url}: {response.text[:200]}"
            )

        return response
