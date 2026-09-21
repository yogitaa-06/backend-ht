import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.queue.client import RedisConfigurationError, redis_settings_from_app


def test_redis_url_is_secret_and_translates_to_arq_settings() -> None:
    settings = Settings(_env_file=None, redis_url="redis://user:password@localhost:6379/2")

    redis = redis_settings_from_app(settings)

    assert redis.host == "localhost"
    assert redis.database == 2
    assert redis.password
    assert redis.password not in repr(settings.redis_url)


def test_worker_configuration_requires_redis_url() -> None:
    with pytest.raises(RedisConfigurationError, match="HIREANDTECH_REDIS_URL"):
        redis_settings_from_app(Settings(_env_file=None, redis_url=None))


def test_lock_ttl_must_exceed_task_timeout() -> None:
    with pytest.raises(ValidationError, match="LOCK_TTL_SECONDS"):
        Settings(
            _env_file=None,
            job_collection_lock_ttl_seconds=60,
            job_collection_task_timeout_seconds=60,
        )


@pytest.mark.parametrize("url", ["http://localhost", "redis://", "not-a-url"])
def test_invalid_redis_url_is_rejected(url: str) -> None:
    with pytest.raises(ValidationError, match="REDIS_URL"):
        Settings(_env_file=None, redis_url=url)
