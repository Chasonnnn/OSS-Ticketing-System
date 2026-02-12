from __future__ import annotations

from app.worker.runner import WorkerConfig, run_worker_forever


def main() -> None:
    run_worker_forever(config=WorkerConfig())


if __name__ == "__main__":
    main()
