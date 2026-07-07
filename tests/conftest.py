from sqlalchemy import text
from sqlalchemy.dialects import registry
from sqlalchemy.testing.plugin.pytestplugin import *  # noqa

registry.register(
    "postgresql.psqlpy", "psqlpy_sqlalchemy.dialect", "PSQLPyAsyncDialect"
)
pytest.register_assert_rewrite("sqlalchemy.testing.assertions")

from sqlalchemy.testing.plugin.pytestplugin import *

from sqlalchemy.testing import provision

_original_temp_table = provision.temp_table_keyword_args
_original_create_db = provision.create_db
_original_drop_db = provision.drop_db
_original_drop_all_schema_objects = provision.drop_all_schema_objects


def temp_table_keyword_args(cfg, eng):
    """Переопределенная функция для psqlpy."""
    if eng.dialect.name == "postgresql":
        return {"prefixes": ["TEMPORARY"]}
    # Вызываем оригинальную для других диалектов
    return _original_temp_table(cfg, eng)


def create_db(cfg, eng, ident):
    if eng.dialect.name == "postgresql":
        from sqlalchemy import create_engine

        template_url = eng.url.set(database="test")
        template_eng = create_engine(template_url)

        try:
            with template_eng.connect() as conn:
                conn.execute(text(f'DROP DATABASE IF EXISTS "{ident}"'))
                conn.execute(text(f'CREATE DATABASE "{ident}"'))
                conn.execute(text("CREATE SCHEMA IF NOT EXISTS test_schema"))
        finally:
            template_eng.dispose()
        test_eng = create_engine(eng.url.set(database=ident))
        try:
            with test_eng.begin() as conn:
                for schema in ["test_schema", "test_schema_2"]:
                    conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
        finally:
            test_eng.dispose()
        return

    return _original_create_db(cfg, eng, ident)


def drop_db(cfg, eng, ident):
    if eng.dialect.name == "postgresql":
        from sqlalchemy import create_engine

        template_url = eng.url.set(database="test")
        template_eng = create_engine(template_url)

        try:
            with template_eng.connect() as conn:
                conn.execute(
                    text(
                        """
                        SELECT pg_terminate_backend(pid)
                        FROM pg_stat_activity
                        WHERE datname = :dbname AND pid <> pg_backend_pid()
                        """
                    ),
                    {"dbname": ident},
                )

                conn.execute(text(f'DROP DATABASE IF EXISTS "{ident}"'))
        finally:
            template_eng.dispose()
        return

    return _original_drop_db(cfg, eng, ident)


provision.temp_table_keyword_args = temp_table_keyword_args
provision.create_db = create_db
provision.drop_db = drop_db


@pytest.fixture(scope="session", autouse=True)
def _patch_is_server_side():
    """Teach ServerSideCursorsTest to recognise psqlpy's server-side cursor.

    Its _is_server_side hardcodes known drivers and returns False for anything
    else (see its own TODO), so a third-party dialect can never be detected.
    psqlpy exposes server_side on its cursor exactly like asyncpg. Patched from
    a fixture, not at import time, so the suite import doesn't run before the
    testing plugin is configured.
    """
    from sqlalchemy.testing.suite import test_results

    original = test_results.ServerSideCursorsTest._is_server_side

    def _is_server_side(self, cursor):
        if self.engine.dialect.driver == "psqlpy":
            return getattr(cursor, "server_side", False)
        return original(self, cursor)

    test_results.ServerSideCursorsTest._is_server_side = _is_server_side


# Known psqlpy driver limitations: substring of the test node id -> reason.
# These need work in the Rust driver, not the dialect, so they are skipped
# rather than left failing.
_DRIVER_LIMITATIONS = {
    # psqlpy encodes interval in the binary format, but a bare literal
    # (SELECT $1) is inferred by the server as text, so the bytes are rejected.
    # Needs the driver to pin the parameter's type oid at prepare time.
    "literal_interval": "psqlpy sends binary interval for a text-inferred bind",
    # psqlpy has no timetz codec (chrono has no timezone-aware time type).
    "TimeTZTest": "psqlpy does not encode/decode TIME WITH TIME ZONE",
    # psqlpy decodes JSON natively, so a custom json_deserializer is never
    # invoked on the result.
    "test_round_trip_custom_json": "psqlpy decodes JSON natively; custom "
    "json_deserializer is not called",
}


# SQLAlchemy's own hook (pulled in via `import *`) generates the backend
# combinations, so delegate to it before adding our skips.
_sqla_modifyitems = pytest_collection_modifyitems


def pytest_collection_modifyitems(session, config, items):
    _sqla_modifyitems(session, config, items)
    for item in items:
        for needle, reason in _DRIVER_LIMITATIONS.items():
            if needle in item.nodeid:
                item.add_marker(pytest.mark.skip(reason=reason))
                break


@pytest.fixture
def anyio_backend() -> str:
    """
    Anyio backend.

    Backend for anyio pytest plugin.
    :return: backend name.
    """
    return "asyncio"
