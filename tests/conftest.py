from sqlalchemy import text
from sqlalchemy.dialects import registry
from sqlalchemy.testing.plugin.pytestplugin import *  # noqa

registry.register("postgresql.psqlpy", "psqlpy_sqlalchemy.dialect", "PSQLPyAsyncDialect")
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
                conn.execute(
                    text(f'DROP DATABASE IF EXISTS "{ident}"')
                )
                conn.execute(
                    text(f'CREATE DATABASE "{ident}"')
                )
                conn.execute(text("CREATE SCHEMA IF NOT EXISTS test_schema"))
        finally:
            template_eng.dispose()
        test_eng = create_engine(eng.url.set(database=ident))
        try:
            with test_eng.begin() as conn:
                for schema in ['test_schema', 'test_schema_2']:
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
                    {"dbname": ident}
                )

                conn.execute(
                    text(f'DROP DATABASE IF EXISTS "{ident}"')
                )
        finally:
            template_eng.dispose()
        return

    return _original_drop_db(cfg, eng, ident)




provision.temp_table_keyword_args = temp_table_keyword_args
provision.create_db = create_db
provision.drop_db = drop_db


@pytest.fixture
def anyio_backend() -> str:
    """
    Anyio backend.

    Backend for anyio pytest plugin.
    :return: backend name.
    """
    return "asyncio"
