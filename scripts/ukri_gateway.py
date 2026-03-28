"""
UKRI Gateway — CLI Entry Point
--------------------------------
Run this script to pull UKRI grant records for a given date and save to Excel.

Usage:
    python scripts/ukri_gateway.py                    # defaults to yesterday
    python scripts/ukri_gateway.py --date 2025-01-10  # specific date
    python scripts/ukri_gateway.py --debug            # verbose logging

Output:
    UKRI_YYYYMMDD.xlsx in the current working directory
    app.log   — full debug log
    error.log — errors only

Note:
    UKRI does not support server-side date filtering. This script scans
    up to 5,000 recent records (50 pages × 100) and filters by the
    'created' timestamp. For most daily runs, far fewer pages are needed.
"""

import argparse
import logging
import sys
from datetime import date, datetime
from pathlib import Path

# Add project root to path so imports work regardless of where script is called from
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from exceptions import APIError, ExcelSaveError  # noqa: E402
from extractors.ukri import UKRIExtractor  # noqa: E402
from utils.logger import setup_logging  # noqa: E402


def parse_args() -> argparse.Namespace:
    """
    Parse command-line arguments.

    Returns:
        Namespace with attributes:
            date  (str | None): Target date string, or None to default to yesterday.
            debug (bool):       Enable verbose console logging.
    """
    parser = argparse.ArgumentParser(
        description="Extract UKRI Gateway grant records to Excel.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/ukri_gateway.py
  python scripts/ukri_gateway.py --date 2025-01-10
  python scripts/ukri_gateway.py --date 2025-01-10 --debug
        """,
    )

    parser.add_argument(
        "--date",
        type=str,
        default=None,
        metavar="YYYY-MM-DD",
        help="Target date to filter grants by created timestamp (default: yesterday)",
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
        extractor = UKRIExtractor(target_date=target_date)
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
