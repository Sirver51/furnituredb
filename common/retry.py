"""Small retry helper for transient HTTP errors during long crawls."""

import time

import httpx

RETRYABLE_STATUS = {404, 408, 429, 500, 502, 503, 504}


def request_with_retry(fn, max_retries=5, base_delay=2.0):
    """Call fn() (a zero-arg callable performing an HTTP request), retrying
    on transient errors with exponential backoff. Re-raises non-retryable
    HTTP errors immediately, and the last error once retries are exhausted."""
    for attempt in range(max_retries):
        try:
            return fn()
        except (httpx.HTTPStatusError, httpx.TransportError) as e:
            if isinstance(e, httpx.HTTPStatusError) and e.response.status_code not in RETRYABLE_STATUS:
                raise
            if attempt == max_retries - 1:
                raise
            delay = base_delay * (2**attempt)
            print(f"  [retry] {e!r}, retrying in {delay:.0f}s (attempt {attempt + 1}/{max_retries})")
            time.sleep(delay)
