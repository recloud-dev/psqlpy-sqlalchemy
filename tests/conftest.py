import pytest
from sqlalchemy.dialects import registry

registry.register("postgresql.psqlpy", "psqlpy_sqlalchemy.dialect", "PSQLPyAsyncDialect")
pytest.register_assert_rewrite("sqlalchemy.testing.assertions")

from sqlalchemy.testing.plugin.pytestplugin import *


@pytest.fixture
def anyio_backend() -> str:
    """
    Anyio backend.

    Backend for anyio pytest plugin.
    :return: backend name.
    """
    return "asyncio"


@pytest.fixture
def postgres_host() -> str:
    return os.environ.get("POSTGRES_HOST", "localhost")


@pytest.fixture
def postgres_user() -> str:
    return os.environ.get("POSTGRES_USER", "postgres")


@pytest.fixture
def postgres_password() -> str:
    return os.environ.get("POSTGRES_PASSWORD", "postgres")


@pytest.fixture
def postgres_port() -> int:
    return int(os.environ.get("POSTGRES_PORT", 5432))


@pytest.fixture
def postgres_dbname() -> str:
    return os.environ.get("POSTGRES_DBNAME", "psqlpy_sqlalchemy_test")
