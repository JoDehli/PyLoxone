from custom_components.test.fuzzing.fuzzer_utils.GreyBoxFuzzer import GreyBoxFuzzer
from custom_components.test.fuzzing.fuzzer_utils.GreyBoxRunner import GreyBoxRunner
from custom_components.test.fuzzing.fuzzer_utils.fuzzer_tools.Seed import Seed
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
    seed_population: list[Seed]
    result: dict

    seed_population = grey_box_fuzzer.fuzz(seed_template, seed_specification, 20)
    result = grey_box_runner.run(demo_function, seed_population, 100)

    assert result["failed_tests"] == 0


@pytest.mark.skipif(False, reason="Not skiped!")
def test_map_range() -> None:
    logger.info("Start of test_map_range() test.")
    seed_template = ["FLOAT", "FLOAT", "FLOAT", "FLOAT", "FLOAT"]
    seed_specification = ['r', 'r', 'r', 'r', 'r']
    seed_population: list[Seed]
    result: dict

    seed_population = grey_box_fuzzer.fuzz(seed_template, seed_specification, 20)
    result = grey_box_runner.run(map_range, seed_population, 100)

    assert result["failed_tests"] == 0


@pytest.mark.skipif(False, reason="Not skiped!")
def test_hass_to_lox() -> None:
    logger.info("Start of test_hass_to_lox() test.")
    seed_template = ["FLOAT"]
    seed_specification = ['r']
    seed_population: list[Seed]
    result: dict

    seed_population = grey_box_fuzzer.fuzz(seed_template, seed_specification, 20)
    result = grey_box_runner.run(hass_to_lox, seed_population, 100)

    assert result["failed_tests"] == 0


@pytest.mark.skipif(False, reason="Not skiped!")
def test_lox_to_hass() -> None:
    logger.info("Start of test_lox_to_hass() test.")
    seed_template = ["FLOAT"]
    seed_specification = ['r']
    seed_population: list[Seed]
    result: dict

    seed_population = grey_box_fuzzer.fuzz(seed_template, seed_specification, 20)
    result = grey_box_runner.run(lox_to_hass, seed_population, 100)

    assert result["failed_tests"] == 0


@pytest.mark.skipif(False, reason="Not skiped!")
def test_lox2lox_mapped() -> None:
    logger.info("Start of test_lox2lox_mapped() test.")
    seed_template = ["FLOAT", "FLOAT", "FLOAT"]
    seed_specification = ['r', 'r', 'r']
    seed_population: list[Seed]
    result: dict

    seed_population = grey_box_fuzzer.fuzz(seed_template, seed_specification, 20)
    result = grey_box_runner.run(lox2lox_mapped, seed_population, 100)

    assert result["failed_tests"] == 0


@pytest.mark.skipif(False, reason="Not skiped!")
def test_lox2hass_mapped() -> None:
    logger.info("Start of test_lox2hass_mapped() test.")
    seed_template = ["FLOAT", "FLOAT", "FLOAT"]
    seed_specification = ['r', 'r', 'r']
    seed_population: list[Seed]
    result: dict

    seed_population = grey_box_fuzzer.fuzz(seed_template, seed_specification, 20)
    result = grey_box_runner.run(lox2hass_mapped, seed_population, 100)

    assert result["failed_tests"] == 0


@pytest.mark.skipif(False, reason="Not skiped!")
def test_to_hass_color_temp() -> None:
    logger.info("Start of test_to_hass_color_temp() test.")
    seed_template = ["FLOAT"]
    seed_specification = ['r']
    seed_population: list[Seed]
    result: dict

    seed_population = grey_box_fuzzer.fuzz(seed_template, seed_specification, 20)
    result = grey_box_runner.run(to_hass_color_temp, seed_population, 100)

    assert result["failed_tests"] == 0


@pytest.mark.skipif(False, reason="Not skiped!")
def test_to_loxone_color_temp() -> None:
    logger.info("Start of test_to_loxone_color_temp() test.")
    seed_template = ["FLOAT"]
    seed_specification = ['r']
    seed_population: list[Seed]
    result: dict

    seed_population = grey_box_fuzzer.fuzz(seed_template, seed_specification, 20)
    result = grey_box_runner.run(to_loxone_color_temp, seed_population, 100)

    assert result["failed_tests"] == 0


@pytest.mark.skipif(False, reason="Not skiped!")
def test_get_miniserver_type() -> None:
    logger.info("Start of test_get_miniserver_type() test.")
    seed_template = ["INT"]
    seed_specification = ['r']
    seed_population: list[Seed]
    result: dict

    seed_population = grey_box_fuzzer.fuzz(seed_template, seed_specification, 20)
    result = grey_box_runner.run(get_miniserver_type, seed_population, 100)

    assert result["failed_tests"] == 0
