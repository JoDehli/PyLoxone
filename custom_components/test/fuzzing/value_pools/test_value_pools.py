import pytest
import logging

from custom_components.loxone.helpers import map_range
from custom_components.test.fuzzing.fuzzer_utils.ValuePoolFuzzer import ValuePoolFuzzer
from custom_components.test.fuzzing.fuzzer_utils.ParamRunner import ParamRunner


logger = logging.getLogger(__name__)

value_pool_fuzzer = ValuePoolFuzzer()
param_runner = ParamRunner()


@pytest.mark.timeout(300)
def test_dummy():

    def dummy(a, b, c, d, e):
        return (a / b) + c + d + e

    logger.info("Start of dummy() test.")
    param_set = value_pool_fuzzer.fuzz(5, ["INT", "INT", "INT", "INT", "INT"], 2)
    result = param_runner.run(dummy, param_set)
    logger.info("dummy() test finished.")

    assert result[1] == 0


@pytest.mark.timeout(300)
def test_map_range():
    logger.info("Start of map_range() test.")
    param_set = value_pool_fuzzer.fuzz(5, ["INT", "INT", "INT", "INT", "INT"], 2)
    result = param_runner.run(map_range, param_set)
    logger.info("map_range() test finished.")

    assert result[1] == 0
