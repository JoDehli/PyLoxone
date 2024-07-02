from custom_components.test.fuzzing.fuzzer_utils.GreyBoxFuzzer import GreyBoxFuzzer
from custom_components.test.fuzzing.fuzzer_utils.GreyBoxRunner import GreyBoxRunner
import pytest
import logging

from custom_components.loxone.helpers import (
    map_range,
    hass_to_lox,
    lox_to_hass,
    lox2lox_mapped,
    lox2hass_mapped,
    to_hass_color_temp,
    to_loxone_color_temp,
    get_miniserver_type,
)

logger = logging.getLogger(__name__)
grey_box_fuzzer: GreyBoxFuzzer = GreyBoxFuzzer()
grey_box_runner: GreyBoxRunner = GreyBoxRunner()





# Function to test the grey box fuzzer
def demo_function(s: str) -> None:
    cnt = 0
    if len(s) > 0 and s[0] == 'b':
        cnt += 1
    if len(s) > 1 and s[1] == 'a':
        cnt += 1
    if len(s) > 2 and s[2] == 'd':
        cnt += 1
    if len(s) > 3 and s[3] == '!':
        cnt += 1
    if cnt >= 3:
        raise Exception()


@pytest.mark.skipif(False, reason="Not skiped!")
def test_crashme() -> None:
    logger.info("Start of test_crashme() test.")
    seed_template = ["STRING"]
    seed_specification = [4]


    seed_population = grey_box_fuzzer.fuzz(seed_template, seed_specification, 1)
    result = grey_box_runner.run(demo_function, seed_population, 10)

    assert result["failed_tests"] == 0
