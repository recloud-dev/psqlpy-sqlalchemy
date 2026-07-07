from sqlalchemy.testing.requirements import SuiteRequirements

from sqlalchemy.testing import exclusions


class Requirements(SuiteRequirements):
    @property
    def array_type(self):
        return exclusions.open()

    @property
    def json_type(self):
        return exclusions.open()

    @property
    def datetime_interval(self):
        return exclusions.open()

    @property
    def datetime_timezone(self):
        return exclusions.open()

    @property
    def time_timezone(self):
        return exclusions.open()

    @property
    def date_historic(self):
        return exclusions.open()

    @property
    def datetime_historic(self):
        return exclusions.open()

    @property
    def identity_columns(self):
        return exclusions.open()

    @property
    def computed_columns(self):
        return exclusions.open()

    @property
    def computed_columns_reflect_persisted(self):
        return exclusions.open()

    @property
    def computed_columns_default_persisted(self):
        # PostgreSQL GENERATED columns are always STORED.
        return exclusions.open()

    @property
    def window_functions(self):
        return exclusions.open()

    @property
    def table_value_constructor(self):
        return exclusions.open()

    @property
    def isolation_level(self):
        return exclusions.open()

    @property
    def autocommit(self):
        return exclusions.open()

    @property
    def reflect_tables_no_columns(self):
        return exclusions.open()

    @property
    def percent_schema_names(self):
        return exclusions.open()

    @property
    def bound_limit_offset(self):
        return exclusions.open()

    @property
    def date(self):
        return exclusions.open()

    @property
    def datetime_microseconds(self):
        return exclusions.open()

    @property
    def floats_to_four_decimals(self):
        return exclusions.open()

    @property
    def nullable_booleans(self):
        return exclusions.open()

    @property
    def offset(self):
        return exclusions.open()

    @property
    def parens_in_union_contained_select_w_limit_offset(self):
        return exclusions.open()

    @property
    def precision_generic_float_type(self):
        return exclusions.open()

    @property
    def reflects_pk_names(self):
        return exclusions.open()

    @property
    def sql_expression_limit_offset(self):
        return exclusions.open()

    @property
    def temp_table_reflection(self):
        return exclusions.open()

    @property
    def temp_table_names(self):
        return exclusions.open()

    @property
    def has_temp_table(self):
        return exclusions.open()

    @property
    def temporary_tables(self):
        return exclusions.open()

    @property
    def temporary_views(self):
        return exclusions.open()

    @property
    def time(self):
        return exclusions.open()

    @property
    def time_microseconds(self):
        return exclusions.open()

    @property
    def timestamp_microseconds(self):
        return exclusions.open()

    @property
    def unicode_ddl(self):
        return exclusions.open()

    @property
    def uuid_data_type(self):
        return exclusions.open()

    @property
    def views(self):
        return exclusions.open()

    @property
    def unique_constraints_reflect_as_index(self):
        return exclusions.open()

    @property
    def index_reflects_included_columns(self):
        return exclusions.open()

    @property
    def view_column_reflection(self):
        return exclusions.open()

    @property
    def supports_distinct_on(self):
        return exclusions.open()

    @property
    def ctes(self):
        """Target database supports CTEs"""

        return exclusions.open()

    @property
    def ctes_with_update_delete(self):
        """target database supports CTES that ride on top of a normal UPDATE
        or DELETE statement which refers to the CTE in a correlated subquery.

        """

        return exclusions.open()

    @property
    def ctes_with_values(self):
        """target database supports CTES that ride on top of a VALUES
        clause."""

        return exclusions.open()

    @property
    def ctes_on_dml(self):
        """target database supports CTES which consist of INSERT, UPDATE
        or DELETE *within* the CTE, e.g. WITH x AS (UPDATE....)"""

        return exclusions.open()

    @property
    def autoincrement_insert(self):
        """target platform generates new surrogate integer primary key values
        when insert() is executed, excluding the pk column."""

        return exclusions.open()
