import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, exc, testing
from sqlalchemy.testing import async_test, fixtures

pytestmark = pytest.mark.anyio


class PSQLPyAsyncDialectTest(fixtures.TestBase):
    __only_on__ = "postgresql+psqlpy"

    def test_example(self):
        pytest.fail("failed example of dialect test")
