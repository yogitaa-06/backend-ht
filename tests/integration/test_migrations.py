import os
import subprocess
import sys

import pytest

TEST_DATABASE_URL = os.getenv("HIREANDTECH_TEST_DATABASE_URL")


@pytest.mark.skipif(
    TEST_DATABASE_URL is None,
    reason="HIREANDTECH_TEST_DATABASE_URL is not configured",
)
@pytest.mark.database
def test_alembic_upgrade_downgrade_and_reupgrade_succeed() -> None:
    assert TEST_DATABASE_URL is not None

    env = os.environ.copy()
    env["HIREANDTECH_ENVIRONMENT"] = "test"
    env["HIREANDTECH_DATABASE_URL"] = TEST_DATABASE_URL
    env["HIREANDTECH_DATABASE_MIGRATION_URL"] = TEST_DATABASE_URL
    env["HIREANDTECH_DATABASE_SSL_MODE"] = "disable"

    for arguments in (
        ("upgrade", "head"),
        ("downgrade", "0004_resumes"),
        ("upgrade", "head"),
        ("downgrade", "0003_ip_security"),
        ("upgrade", "head"),
        ("current",),
    ):
        result = subprocess.run(  # noqa: S603 - arguments are fixed test constants.
            [sys.executable, "-m", "alembic", *arguments],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert result.returncode == 0, f"Alembic {' '.join(arguments)} failed"
        if arguments == ("current",):
            assert "0005_phase5_hardening (head)" in result.stdout
