from __future__ import annotations

from collections.abc import Generator

import httpx


def get_http_client() -> Generator[httpx.Client, None, None]:
    # Centralize HTTP client configuration (timeouts, etc) so we can override in tests.
    with httpx.Client(timeout=10.0) as client:
        yield client
