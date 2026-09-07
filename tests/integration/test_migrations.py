import os
import subprocess
import sys

import pytest

TEST_DATABASE_URL = os.getenv("HIREANDTECH_TEST_DATABASE_URL")


@pytest.mark.skipif(
    TEST_DATABASE_URL is None,
    reason="HIREANDTECH_TEST_DATABASE_URL is not configured",
)
def test_alembic_upgrade_head_succeeds() -> None:
    assert TEST_DATABASE_URL is not None

    env = os.environ.copy()
    env["HIREANDTECH_ENVIRONMENT"] = "test"
    env["HIREANDTECH_DATABASE_URL"] = TEST_DATABASE_URL
    env["HIREANDTECH_DATABASE_MIGRATION_URL"] = TEST_DATABASE_URL
    env["HIREANDTECH_DATABASE_SSL_MODE"] = "disable"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "upgrade",
            "head",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, (
        f"Alembic migration failed.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
