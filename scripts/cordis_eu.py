"""
CORDIS EU — CLI Entry Point
-----------------------------
Run this script to pull EU grant records from CORDIS for a given date window
and save to Excel.

Usage:
    python scripts/cordis_eu.py                    # defaults to yesterday as end date
    python scripts/cordis_eu.py --date 2025-01-10  # specific end date (7-day window)
    python scripts/cordis_eu.py --debug            # verbose logging

Output:
    CORDIS_YYYYMMDD.xlsx in the current working directory
    app.log   — full debug log
    error.log — errors only

Note:
    CORDIS is a weekly cadence source. The script pulls records updated
    in the 7 days up to --date. Run once per week.

    If requests time out, the CORDIS server may be geo-restricted
    on your current network. Try from a different network or EU VPN.
"""

import argparse
import logging
import sys
from datetime import date, datetime
from pathlib import Path

# Add project root to path so imports work regardless of where script is called from
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from exceptions import APIError, ExcelSaveError  # noqa: E402
from extractors.cordis import CORDISExtractor  # noqa: E402
from utils.logger import setup_logging  # noqa: E402


def parse_args() -> argparse.Namespace:
    """
    Parse command-line arguments.

    Returns:
        Namespace with attributes:
            date  (str | None): Target end date string, or None to default to yesterday.
            debug (bool):       Enable verbose console logging.
    """
    parser = argparse.ArgumentParser(
        description="Extract CORDIS EU grant records to Excel (7-day window).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/cordis_eu.py
  python scripts/cordis_eu.py --date 2025-01-10
  python scripts/cordis_eu.py --date 2025-01-10 --debug
        """,
    )

    parser.add_argument(
        "--date",
        type=str,
        default=None,
        metavar="YYYY-MM-DD",
        help="End date of the 7-day pull window (default: yesterday)",
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        default=False,
        help="Enable DEBUG-level console output",
    )

    return parser.parse_args()


def resolve_date(date_str: str | None) -> date | None:
    """
    Parse the --date argument string into a date object.

    Args:
        date_str: String in 'YYYY-MM-DD' format, or None.

    Returns:
        A date object, or None (BaseExtractor will default to yesterday).

    Raises:
        SystemExit: If the date string is in the wrong format.
    """
    if date_str is None:
        return None

    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        print(f"ERROR: Invalid date format '{date_str}'. Expected YYYY-MM-DD.")
        sys.exit(1)


def main() -> None:
    """
    Main entry point — parse args, run extractor, report result.

    Exit codes:
        0 — success
        1 — any error (API failure, Excel save failure, unexpected error)
    """
    args = parse_args()
    setup_logging(debug=args.debug)

    logger = logging.getLogger(__name__)

    target_date = resolve_date(args.date)

    try:
        extractor = CORDISExtractor(target_date=target_date)
        output_file = extractor.run()
        logger.info(f"Done. Output saved to: {output_file}")
        sys.exit(0)

    except ExcelSaveError as e:
        logger.error(f"Could not save Excel file — {e}")
        sys.exit(1)

    except APIError as e:
        logger.error(f"API extraction failed — {e}")
        sys.exit(1)

    except Exception as e:
        logger.exception(f"Unexpected failure — {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
