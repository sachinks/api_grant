import pandas as pd
from exceptions import ExcelSaveError


# These are the exact column names the client expects — do not change.
OUTPUT_COLUMNS = [
    "FIRST",
    "LAST",
    "INSTITUTION",
    "TITLE",
    "FUNDING_AMT",
    "CURRENCY",
    "AWARD_DATE",
    "SOURCE",
    "LINK",
]


def save_to_excel(records: list[dict], filepath: str) -> None:
    """
    Save a list of grant records to an .xlsx file.

    Each record must be a dict with keys matching OUTPUT_COLUMNS.
    Missing fields are filled with an empty string — never crash on missing data.

    Args:
        records:  List of dicts, one per grant award.
        filepath: Full path to the output .xlsx file.

    Raises:
        ExcelSaveError: If the file cannot be written.
    """
    try:
        # Build DataFrame — reindex forces exact column order and fills gaps
        df = pd.DataFrame(records)
        df = df.reindex(columns=OUTPUT_COLUMNS, fill_value="")

        df.to_excel(filepath, index=False, engine="openpyxl")

    except Exception as e:
        raise ExcelSaveError(f"Failed to save Excel file '{filepath}': {e}") from e
