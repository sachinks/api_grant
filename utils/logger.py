import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

# All log files go into this folder, created automatically if missing
LOGS_DIR = Path("logs")


def setup_logging(debug: bool = False) -> None:
    """
    Configure application logging with multiple handlers and rotation.

    Log files are written to the logs/ directory in the working directory.
    The directory is created automatically if it does not exist.

    Args:
        debug (bool): Enable DEBUG logs in console if True, else INFO only.
    """

    # Create logs/ directory if it doesn't exist
    LOGS_DIR.mkdir(exist_ok=True)

    # Master logger
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)  # Always keep lowest here

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    # Rotating App Log (all logs)
    app_handler = RotatingFileHandler(
        LOGS_DIR / "app.log", maxBytes=5_000_000, backupCount=3
    )
    app_handler.setLevel(logging.DEBUG)
    app_handler.setFormatter(formatter)

    # Rotating Error Log (errors only)
    error_handler = RotatingFileHandler(
        LOGS_DIR / "error.log", maxBytes=2_000_000, backupCount=2
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)

    # Console Handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG if debug else logging.INFO)
    console_handler.setFormatter(formatter)

    # Clear old handlers to avoid duplicate logs on re-init
    logger.handlers.clear()

    logger.addHandler(app_handler)
    logger.addHandler(error_handler)
    logger.addHandler(console_handler)
