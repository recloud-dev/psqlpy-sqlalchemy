# from sqlalchemy.testing.suite import *  # noqa: F401,F403
from sqlalchemy.testing.suite import NumericTest as _NumericTest

class NumericTest(_NumericTest):
    def test_decimal_coerce_round_trip(self, connection):
        super().test_decimal_coerce_round_trip(connection)
        
    def test_render_literal_numeric(self, literal_round_trip):
        super().test_render_literal_numeric(literal_round_trip)
        
    def test_float_as_decimal(self, do_numeric_test):
        super().test_float_as_decimal(do_numeric_test)