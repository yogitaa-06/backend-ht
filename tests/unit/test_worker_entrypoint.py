import importlib

import pytest


def test_worker_entrypoint_registers_task_and_scheduler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HIREANDTECH_REDIS_URL", "redis://localhost:6379/0")
    worker = importlib.import_module("app.queue.worker")

    assert worker.WorkerSettings.queue_name == "hireandtech:jobs"
    assert len(worker.WorkerSettings.functions) == 1
    assert len(worker.WorkerSettings.cron_jobs) == 2
    assert worker.WorkerSettings.on_startup is worker.startup
    assert worker.WorkerSettings.on_shutdown is worker.shutdown


@pytest.mark.anyio
async def test_scrape_worker_startup_success() -> None:
    from unittest.mock import AsyncMock

    from app.queue.workers.scrape import startup

    ctx = {"redis": AsyncMock()}

    with pytest.MonkeyPatch.context() as m:
        fake_db = AsyncMock()
        fake_db.check_connection.return_value = True
        m.setattr("app.queue.workers.scrape.Database", lambda s: fake_db)

        await startup(ctx)

    assert "settings" in ctx
    assert "database" in ctx
    assert "collector_registry" in ctx
    assert "collection_coordinator" in ctx
    assert "collection_locks" in ctx


@pytest.mark.anyio
async def test_scrape_worker_startup_failure() -> None:
    from unittest.mock import AsyncMock

    from app.queue.workers.scrape import startup

    ctx = {"redis": AsyncMock()}

    with pytest.MonkeyPatch.context() as m:
        fake_db = AsyncMock()
        fake_db.check_connection.return_value = False
        m.setattr("app.queue.workers.scrape.Database", lambda s: fake_db)

        with pytest.raises(RuntimeError, match="Database is unavailable"):
            await startup(ctx)


@pytest.mark.anyio
async def test_scrape_worker_shutdown() -> None:
    from unittest.mock import AsyncMock

    from app.db.session import Database
    from app.queue.workers.scrape import shutdown

    fake_db = AsyncMock(spec=Database)
    ctx = {"database": fake_db}

    await shutdown(ctx)
    fake_db.close.assert_awaited_once()
