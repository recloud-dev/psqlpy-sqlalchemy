import decimal
import typing as t
import uuid
from collections import deque
from collections.abc import MutableMapping, Sequence
from types import ModuleType
from typing import Any, Optional, Tuple, Type

import psqlpy
from psqlpy import exceptions as psqlpy_exceptions
from sqlalchemy import URL, AsyncAdaptedQueuePool, Pool, util
from sqlalchemy.connectors.asyncio import (
    AsyncAdapt_dbapi_connection,
    AsyncAdapt_dbapi_cursor,
    AsyncAdapt_dbapi_ss_cursor,
)
from sqlalchemy.dialects.postgresql import BYTEA, OID, REGCLASS
from sqlalchemy.dialects.postgresql.base import INTERVAL, PGDialect, PGExecutionContext
from sqlalchemy.dialects.postgresql.json import JSON, JSONB, JSONPathType
from sqlalchemy.engine import processors
from sqlalchemy.sql import sqltypes
from sqlalchemy.util.concurrency import await_only

if t.TYPE_CHECKING:
    from sqlalchemy.engine.interfaces import DBAPICursor, _DBAPICursorDescription

# Sentinel stored on the connection when SQLAlchemy asks for AUTOCOMMIT: no
# psqlpy transaction is opened and every statement auto-commits.
_AUTOCOMMIT = "AUTOCOMMIT"

# PEP-249 exception classes to lift from psqlpy.exceptions onto the DBAPI facade
# (psqlpy re-exports only Error at the top level).
_PEP249_EXCEPTIONS = (
    "Error",
    "InterfaceError",
    "DatabaseError",
    "DataError",
    "OperationalError",
    "IntegrityError",
    "InternalError",
    "ProgrammingError",
    "NotSupportedError",
)

_SSL_MODE_MAP = {
    "disable": psqlpy.SslMode.Disable,
    "allow": psqlpy.SslMode.Allow,
    "prefer": psqlpy.SslMode.Prefer,
    "require": psqlpy.SslMode.Require,
    "verify-ca": psqlpy.SslMode.VerifyCa,
    "verify-full": psqlpy.SslMode.VerifyFull,
}
_TARGET_SESSION_ATTRS_MAP = {
    "any": psqlpy.TargetSessionAttrs.Any,
    "read-write": psqlpy.TargetSessionAttrs.ReadWrite,
    "read-only": psqlpy.TargetSessionAttrs.ReadOnly,
}
_LOAD_BALANCE_HOSTS_MAP = {
    "disable": psqlpy.LoadBalanceHosts.Disable,
    "random": psqlpy.LoadBalanceHosts.Random,
}


class _PGString(sqltypes.String):
    render_bind_cast = True


class _PGJSONIntIndexType(sqltypes.JSON.JSONIntIndexType):
    __visit_name__ = "json_int_index"

    render_bind_cast = True


class _PGJSONStrIndexType(sqltypes.JSON.JSONStrIndexType):
    __visit_name__ = "json_str_index"

    render_bind_cast = True


class _PGJSONPathType(JSONPathType):
    pass


class _PGJSON(JSON):
    # psqlpy decodes JSON/JSONB columns into Python objects already, so skip the
    # base json.loads result processor.
    def result_processor(self, dialect, coltype):
        return None


class _PGJSONB(JSONB):
    def result_processor(self, dialect, coltype):
        return None


class _PGInterval(INTERVAL):
    render_bind_cast = True


class _PGTimeStamp(sqltypes.DateTime):
    render_bind_cast = True


class _PGDate(sqltypes.Date):
    render_bind_cast = True


class _PGTime(sqltypes.Time):
    render_bind_cast = True


class _PGInteger(sqltypes.Integer):
    render_bind_cast = True


class _PGSmallInteger(sqltypes.SmallInteger):
    render_bind_cast = True


class _PGNullType(sqltypes.NullType):
    render_bind_cast = True


class _PGBigInteger(sqltypes.BigInteger):
    render_bind_cast = True


class _PGBoolean(sqltypes.Boolean):
    render_bind_cast = True


class _PGRegclass(REGCLASS):
    render_bind_cast = True


class _PGOID(OID):
    render_bind_cast = True


class _PGLargeBinary(BYTEA):
    # Emit $n::BYTEA so multi-row insertmanyvalues params type as bytea instead
    # of being inferred as text.
    render_bind_cast = True


class _PGNumericCommon(sqltypes.Numeric):
    # NUMERIC/DECIMAL columns: psqlpy encodes them only from Decimal and decodes
    # them back as Decimal, so bind coerces to Decimal and result is a no-op
    # unless the caller asked for float.
    render_bind_cast = True

    def bind_processor(self, dialect):
        def process(value):
            if value is None or isinstance(value, decimal.Decimal):
                return value
            return decimal.Decimal(str(value))

        return process

    def result_processor(self, dialect, coltype):
        if self.asdecimal:
            return None
        return processors.to_float


class _PGNumeric(_PGNumericCommon, sqltypes.NUMERIC):
    render_bind_cast = True


class _PGFloat(_PGNumericCommon, sqltypes.Float):
    # FLOAT columns are float8: psqlpy encodes/decodes them as Python float, so
    # the coercions run the opposite way to NUMERIC.
    render_bind_cast = True

    def bind_processor(self, dialect):
        def process(value):
            if value is None or isinstance(value, float):
                return value
            return float(value)

        return process

    def result_processor(self, dialect, coltype):
        if self.asdecimal:
            return processors.to_decimal_processor_factory(
                decimal.Decimal, self._effective_decimal_return_scale
            )
        return None


class _PGDecimal(_PGNumericCommon, sqltypes.DECIMAL):
    render_bind_cast = True


class _PSQLPyUUID(PGDialect.colspecs[sqltypes.Uuid]):
    def result_processor(self, dialect, coltype):
        # PSQLPy returns UUID columns as str; rebuild uuid.UUID when as_uuid.
        if self.as_uuid:

            def process(value):
                if value is not None and not isinstance(value, uuid.UUID):
                    value = uuid.UUID(value)
                return value

            return process

        def process(value):
            if value is not None and isinstance(value, uuid.UUID):
                value = str(value)
            return value

        return process


class PGExecutionContext_psqlpy(PGExecutionContext):
    def create_server_side_cursor(self) -> "DBAPICursor":
        return self._dbapi_connection.cursor(server_side=True)

    def pre_exec(self) -> None:
        # DDL can change a table's result type out from under psqlpy's cached
        # prepared plans; bump the dialect-wide marker so every connection drops
        # its statement cache before its next prepare (mirrors asyncpg).
        if self.isddl:
            self.dialect._invalidate_schema_cache()
        self.cursor._invalidate_schema_cache_asof = (
            self.dialect._invalidate_schema_cache_asof
        )

    def handle_dbapi_exception(self, e: Exception) -> None:
        if isinstance(e, self.dialect.dbapi.DatabaseError) and (
            "cached plan must not change result type" in str(e)
        ):
            self.dialect._invalidate_schema_cache()


class AsyncAdapt_psqlpy_cursor(AsyncAdapt_dbapi_cursor):
    __slots__ = (
        "_arraysize",
        "_description",
        "_invalidate_schema_cache_asof",
        "_rowcount",
    )

    _adapt_connection: "AsyncAdapt_psqlpy_connection"
    _connection: psqlpy.Connection

    def __init__(self, adapt_connection: AsyncAdapt_dbapi_connection):
        self._adapt_connection = adapt_connection
        self._connection = adapt_connection._connection
        self._rows = deque()
        self._description: t.Optional[t.List[t.Tuple[t.Any, ...]]] = None
        self._arraysize = 1
        self._rowcount = -1
        self._invalidate_schema_cache_asof = 0

    async def _prepare_execute(
        self,
        querystring: str,
        parameters: t.Union[t.Sequence[t.Any], t.Mapping[str, Any], None] = None,
    ) -> None:
        if not self._adapt_connection._started:
            await self._adapt_connection._start_transaction()

        await self._adapt_connection._invalidate_schema_cache(
            self._invalidate_schema_cache_asof
        )

        prepared_stmt = await self._connection.prepare(
            querystring=querystring,
            parameters=parameters,
        )
        # psqlpy.Column exposes only name and table_oid (no type OID), so the
        # type_code slot stays None; result processors rely on native decoding.
        # No columns means a non-returning statement: leave description None so
        # SQLAlchemy reports returns_rows=False.
        columns = prepared_stmt.columns()
        self._description = [
            (column.name, None, None, None, None, None, None) for column in columns
        ] or None

        if self.server_side:
            self._cursor = self._connection.cursor(
                querystring,
                parameters,
            )
            await self._cursor.start()
            self._rowcount = -1
            return

        results = await prepared_stmt.execute()
        affected = results.rows_affected
        self._rowcount = affected if affected is not None else -1
        # result(as_tuple=True) reads values positionally, so duplicate column
        # names survive (row_factory routes through a name-keyed dict and drops
        # them).
        self._rows = deque(results.result(as_tuple=True))

    @property
    def description(self) -> "Optional[_DBAPICursorDescription]":
        return self._description

    @property
    def rowcount(self) -> int:
        return self._rowcount

    @property
    def arraysize(self) -> int:
        return self._arraysize

    @arraysize.setter
    def arraysize(self, value: int) -> None:
        self._arraysize = value

    async def _executemany(
        self,
        operation: str,
        seq_of_parameters: t.Sequence[t.Sequence[t.Any]],
    ) -> None:
        adapt_connection = self._adapt_connection

        self._description = None

        if not adapt_connection._started:
            await adapt_connection._start_transaction()

        await adapt_connection._invalidate_schema_cache(
            self._invalidate_schema_cache_asof
        )

        return await self._connection.execute_many(
            operation, seq_of_parameters, prepared=True
        )

    def execute(
        self,
        operation: t.Any,
        parameters: t.Union[t.Sequence[t.Any], t.Mapping[str, Any], None] = None,
    ) -> None:
        await_only(self._prepare_execute(operation, parameters))

    def executemany(self, operation, seq_of_parameters) -> None:
        return await_only(self._executemany(operation, seq_of_parameters))

    def setinputsizes(self, *inputsizes):
        raise NotImplementedError


class AsyncAdapt_psqlpy_ss_cursor(
    AsyncAdapt_dbapi_ss_cursor,
    AsyncAdapt_psqlpy_cursor,
):
    _cursor: psqlpy.Cursor

    def __init__(self, adapt_connection):
        self._adapt_connection = adapt_connection
        self._connection = adapt_connection._connection
        self.await_ = adapt_connection.await_
        self._rows = deque()
        self._description = None
        self._arraysize = 1
        self._rowcount = -1
        self._invalidate_schema_cache_asof = 0

        self._cursor = self._connection.cursor()

    def _convert_result(
        self,
        result: psqlpy.QueryResult,
    ) -> Tuple[Tuple[Any, ...], ...]:
        return tuple(result.result(as_tuple=True))

    def close(self):
        if self._cursor is not None:
            self._cursor.close()
            self._cursor = None

    def fetchone(self):
        result = self.await_(self._cursor.fetchone())
        return self._convert_result(result=result)

    def fetchmany(self, size=None):
        result = self.await_(self._cursor.fetchmany(size=size))
        return self._convert_result(result=result)

    def fetchall(self):
        result = self.await_(self._cursor.fetchall())
        return self._convert_result(result=result)

    def __iter__(self):
        iterator = self._cursor.__aiter__()
        while True:
            try:
                result = self.await_(iterator.__anext__())
                rows = self._convert_result(result=result)
                yield rows
            except StopAsyncIteration:
                break


class AsyncAdapt_psqlpy_connection(AsyncAdapt_dbapi_connection):
    _cursor_cls = AsyncAdapt_psqlpy_cursor
    _ss_cursor_cls = AsyncAdapt_psqlpy_ss_cursor

    _connection: psqlpy.Connection

    __slots__ = (
        "_invalidate_schema_cache_asof",
        "_isolation_setting",
        "_prepared_statement_cache",
        "_prepared_statement_name_func",
        "_started",
        "_transaction",
        "deferrable",
        "isolation_level",
        "readonly",
    )

    def __init__(self, dbapi, connection):
        super().__init__(dbapi, connection)
        self.isolation_level = self._isolation_setting = None
        self.readonly = False
        self.deferrable = False
        self._transaction = None
        self._started = False
        self._invalidate_schema_cache_asof = 0

    async def _invalidate_schema_cache(self, asof: int) -> None:
        # Drop psqlpy's prepared-statement cache once per DDL marker, so a plan
        # cached before a table was redefined is never executed.
        if asof > self._invalidate_schema_cache_asof:
            await self._connection.clear_statement_cache()
            self._invalidate_schema_cache_asof = asof

    async def _start_transaction(self) -> None:
        if self._isolation_setting is _AUTOCOMMIT:
            self._started = True
            return

        transaction = self._connection.transaction(
            isolation_level=self._isolation_setting,
            read_variant=psqlpy.ReadVariant.ReadOnly if self.readonly else None,
            deferrable=self.deferrable,
        )
        await transaction.begin()
        self._transaction = transaction
        self._started = True

    def set_isolation_level(self, level):
        if self._started:
            self.rollback()
        self.isolation_level = self._isolation_setting = level

    def rollback(self) -> None:
        if not self._started:
            return

        if self._transaction is not None:
            await_only(self._transaction.rollback())
        self._transaction = None
        self._started = False

    def commit(self) -> None:
        if not self._started:
            return

        if self._transaction is not None:
            await_only(self._transaction.commit())
        self._transaction = None
        self._started = False

    def close(self):
        self.rollback()
        self._connection.close()

    def cursor(self, server_side=False):
        if server_side:
            return self._ss_cursor_cls(self)
        return self._cursor_cls(self)


class PSQLPyAdaptDBAPI:
    def __init__(self, psqlpy) -> None:
        self.psqlpy = psqlpy
        self.paramstyle = "numeric_dollar"

        for k, v in self.psqlpy.__dict__.items():
            if k != "connect":
                self.__dict__[k] = v

        # SQLAlchemy expects the full PEP-249 hierarchy on the DBAPI module for
        # error wrapping and is_disconnect; psqlpy only re-exports Error itself.
        self.Warning = psqlpy_exceptions.WarningError
        for name in _PEP249_EXCEPTIONS:
            self.__dict__[name] = getattr(psqlpy_exceptions, name)

    def connect(self, *arg, **kw):
        creator_fn = kw.pop("async_creator_fn", self.psqlpy.connect)
        return AsyncAdapt_psqlpy_connection(self, await_only(creator_fn(*arg, **kw)))

    @staticmethod
    def Binary(value):
        # psqlpy encodes bytea from bytes; it has no memoryview converter.
        return bytes(value)


class PSQLPyAsyncDialect(PGDialect):
    driver = "psqlpy"
    is_async = True

    execution_ctx_cls = PGExecutionContext_psqlpy
    supports_statement_cache = True
    supports_server_side_cursors = True
    default_paramstyle = "numeric_dollar"
    # QueryResult reports the command-tag row count, so single-statement
    # rowcount is accurate; execute_many discards it, so multi stays unset.
    supports_sane_rowcount = True
    supports_sane_multi_rowcount = False

    colspecs = util.update_copy(
        PGDialect.colspecs,
        {
            sqltypes.String: _PGString,
            sqltypes.JSON: _PGJSON,
            JSONB: _PGJSONB,
            sqltypes.JSON.JSONPathType: _PGJSONPathType,
            sqltypes.JSON.JSONIntIndexType: _PGJSONIntIndexType,
            sqltypes.JSON.JSONStrIndexType: _PGJSONStrIndexType,
            sqltypes.Interval: _PGInterval,
            INTERVAL: _PGInterval,
            sqltypes.Date: _PGDate,
            sqltypes.DateTime: _PGTimeStamp,
            sqltypes.Time: _PGTime,
            sqltypes.Integer: _PGInteger,
            sqltypes.SmallInteger: _PGSmallInteger,
            sqltypes.BigInteger: _PGBigInteger,
            REGCLASS: _PGRegclass,
            OID: _PGOID,
            sqltypes.Numeric: _PGNumeric,
            sqltypes.Float: _PGFloat,
            sqltypes.DECIMAL: _PGDecimal,
            sqltypes.Uuid: _PSQLPyUUID,
            sqltypes.LargeBinary: _PGLargeBinary,
        },
    )

    def __init__(self, *args, **kw):
        super().__init__(*args, **kw)
        # Monotonic marker bumped on every DDL; connections clear their psqlpy
        # statement cache when they observe a newer value.
        self._invalidate_schema_cache_asof = 0

    def _invalidate_schema_cache(self) -> None:
        self._invalidate_schema_cache_asof += 1

    def get_dialect_pool_class(self, url: URL) -> Type[Pool]:
        return AsyncAdaptedQueuePool

    @classmethod
    def import_dbapi(cls) -> ModuleType:
        return t.cast(ModuleType, PSQLPyAdaptDBAPI(__import__("psqlpy")))

    @util.memoized_property
    def _isolation_lookup(self) -> t.Dict[str, t.Any]:
        return {
            "AUTOCOMMIT": _AUTOCOMMIT,
            "READ COMMITTED": psqlpy.IsolationLevel.ReadCommitted,
            "READ UNCOMMITTED": psqlpy.IsolationLevel.ReadUncommitted,
            "REPEATABLE READ": psqlpy.IsolationLevel.RepeatableRead,
            "SERIALIZABLE": psqlpy.IsolationLevel.Serializable,
        }

    def get_isolation_level_values(self, dbapi_connection):
        return list(self._isolation_lookup)

    def set_isolation_level(
        self,
        dbapi_connection: AsyncAdapt_psqlpy_connection,
        level,
    ):
        dbapi_connection.set_isolation_level(self._isolation_lookup[level])

    def set_readonly(self, connection, value):
        connection.readonly = bool(value)

    def get_readonly(self, connection):
        return connection.readonly

    def set_deferrable(self, connection, value):
        connection.deferrable = value

    def get_deferrable(self, connection):
        return connection.deferrable

    def is_disconnect(self, e, connection, cursor):
        if isinstance(e, psqlpy_exceptions.BaseConnectionError):
            return True
        if connection is not None:
            return connection._connection.is_closed()
        return False

    def create_connect_args(
        self,
        url: URL,
    ) -> Tuple[Sequence[str], MutableMapping[str, Any]]:
        opts = url.translate_connect_args(database="db_name")
        kwargs = {k: v for k, v in opts.items() if v is not None}

        query = url.query
        if "ssl_mode" in query:
            kwargs["ssl_mode"] = _SSL_MODE_MAP[query["ssl_mode"].lower()]
        if "ca_file" in query:
            kwargs["ca_file"] = query["ca_file"]
        if "application_name" in query:
            kwargs["application_name"] = query["application_name"]
        if "connect_timeout" in query:
            kwargs["connect_timeout_sec"] = int(query["connect_timeout"])
        if "target_session_attrs" in query:
            kwargs["target_session_attrs"] = _TARGET_SESSION_ATTRS_MAP[
                query["target_session_attrs"].lower()
            ]
        if "load_balance_hosts" in query:
            kwargs["load_balance_hosts"] = _LOAD_BALANCE_HOSTS_MAP[
                query["load_balance_hosts"].lower()
            ]
        if "options" in query:
            kwargs["options"] = query["options"]

        return ([], kwargs)


dialect = PSQLPyAsyncDialect
