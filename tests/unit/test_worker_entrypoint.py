import importlib

import pytest


def test_worker_entrypoint_registers_task_and_scheduler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HIREANDTECH_REDIS_URL", "redis://localhost:6379/0")
    worker = importlib.import_module("app.queue.worker")

    assert worker.WorkerSettings.queue_name == "hireandtech:jobs"
    assert len(worker.WorkerSettings.functions) == 1
    assert len(worker.WorkerSettings.cron_jobs) == 1
    assert worker.WorkerSettings.on_startup is worker.startup
    assert worker.WorkerSettings.on_shutdown is worker.shutdown
