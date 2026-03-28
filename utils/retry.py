import time
from exceptions import APIRequestError


def retry(func):
    """
    Retry decorator for handling transient API failures.
    Only retries APIRequestError (network timeouts, 5xx errors).
    Non-retryable errors (bad data, file save) fail immediately.
    """

    def wrapper(self, *args, **kwargs):
        for attempt in range(1, self.retries + 1):
            try:
                self.logger.debug(
                    f"{func.__name__} attempt {attempt}/{self.retries}"
                )
                return func(self, *args, **kwargs)

            except APIRequestError as e:
                self.logger.warning(
                    f"{func.__name__} request error on attempt {attempt}: {e}"
                )

                if attempt == self.retries:
                    # Use error() not exception() — full traceback goes to
                    # error.log via the file handler; no need to flood console
                    self.logger.error(
                        f"{func.__name__} failed after {self.retries} attempts"
                    )
                    raise

                # Exponential backoff: wait longer on each retry
                time.sleep(self.delay * attempt)

            except Exception as e:
                # Use error() not exception() — keeps console clean.
                # The CLI's logger.exception() will capture the traceback
                # for truly unexpected errors.
                self.logger.error(
                    f"{func.__name__} non-retryable error: {e}"
                )
                raise  # no retry for unexpected errors

        raise RuntimeError(
            f"{func.__name__} failed unexpectedly without returning"
        )

    return wrapper
