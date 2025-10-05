from sqlalchemy import Column
from sqlalchemy import Integer
from sqlalchemy import MetaData
from sqlalchemy import String
from sqlalchemy import Table
from sqlalchemy import exc
from sqlalchemy import testing
from sqlalchemy.testing import async_test
from sqlalchemy.testing import fixtures


class PSQLPyAsyncDialectTest(fixtures.TestBase):
    __only_on__ = "postgresql+psqlpy"

    def test_example(self):
        assert False
