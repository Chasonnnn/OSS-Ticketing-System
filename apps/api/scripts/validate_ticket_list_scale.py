from __future__ import annotations

import os
import statistics
import time

import httpx


def main() -> None:
    base_url = os.environ.get("API_BASE_URL", "http://localhost:8000")
    email = os.environ.get("LOAD_TEST_EMAIL", "load-test-admin@example.com")
    org_name = os.environ.get("LOAD_TEST_ORG", "Load Test Org")
    iterations = int(os.environ.get("LOAD_TEST_ITERATIONS", "50"))

    with httpx.Client(base_url=base_url, timeout=30.0) as client:
        csrf_res = client.get("/auth/csrf")
        csrf_res.raise_for_status()
        csrf = csrf_res.json()["csrf_token"]

        login = client.post(
            "/auth/dev/login",
            json={"email": email, "organization_name": org_name},
            headers={"x-csrf-token": csrf},
        )
        login.raise_for_status()

        samples_ms: list[float] = []
        for _ in range(iterations):
            t0 = time.perf_counter()
            res = client.get("/tickets", params={"limit": 50, "status": "open"})
            res.raise_for_status()
            samples_ms.append((time.perf_counter() - t0) * 1000.0)

    p50 = statistics.median(samples_ms)
    p95 = statistics.quantiles(samples_ms, n=20)[18] if len(samples_ms) >= 20 else max(samples_ms)
    print(f"requests={iterations}")
    print(f"p50_ms={p50:.2f}")
    print(f"p95_ms={p95:.2f}")
    print(f"max_ms={max(samples_ms):.2f}")


if __name__ == "__main__":
    main()
