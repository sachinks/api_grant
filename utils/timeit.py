import time


def timeit(func):
    """
    Measure and log execution time of a function.
    """

    def wrapper(self, *args, **kwargs):
        start_time = time.time()

        try:
            return func(self, *args, **kwargs)

        finally:
            duration = round(time.time() - start_time, 2)
            self.logger.debug(f"{func.__name__} took {duration} seconds")

    return wrapper
