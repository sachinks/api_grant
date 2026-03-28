class APIError(Exception):
    """
    Base exception for all grant extractor errors.
    Catch this to handle any failure in one place.
    """
    pass


class APIRequestError(APIError):
    """
    Raised when an HTTP request to the API fails.
    Retryable — network timeouts and 5xx errors can resolve on retry.
    Examples: connection timeout, 503 Service Unavailable.
    """
    pass


class APIResponseError(APIError):
    """
    Raised when the API returns an unexpected or malformed response.
    Not retryable — retrying won't fix a bad response format.
    Examples: JSON decode error, unexpected status code like 400/404.
    """
    pass


class DataExtractionError(APIError):
    """
    Raised when a single record cannot be mapped to output columns.
    Non-fatal — logged and skipped so the rest of the records still save.
    Examples: missing required field, unexpected data type.
    """
    pass


class ExcelSaveError(APIError):
    """
    Raised when the output .xlsx file cannot be written to disk.
    Not retryable — likely a permissions or disk-space issue.
    """
    pass
