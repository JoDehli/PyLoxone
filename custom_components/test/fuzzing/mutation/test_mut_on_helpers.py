import pytest
import logging
import random

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
from custom_components.test.fuzzing.fuzzer_utils.MutationalFuzzer import (
    MutationalBlackBoxFuzzer,
)
from custom_components.test.fuzzing.fuzzer_utils.GrammarFuzzer import GrammarFuzzer
from custom_components.test.fuzzing.fuzzer_utils.grammars.grammar_ipv4 import (
    grammar_ipv4,
)
from custom_components.test.fuzzing.fuzzer_utils.ParamRunner import ParamRunner


logger = logging.getLogger(__name__)

mutational_fuzzer: MutationalBlackBoxFuzzer = MutationalBlackBoxFuzzer()
grammar_fuzzer: GrammarFuzzer = GrammarFuzzer()
param_runner: ParamRunner = ParamRunner()


@pytest.mark.skipif(True, reason="Only dummy test case.")
def test_demo_get_param_set() -> None:
    # get a list of valid grammar outputs
    full_grammar_cov: list = grammar_fuzzer.fuzz_grammar_coverage(
        grammar_ipv4, "<IPv4>"
    )
    # choose randomly on value
    random_valid_grammar_string = random.choice(full_grammar_cov)

    # If the grammar value should be an int or float, you have to cast the string first.
    # Get the param_set.
    mutational_fuzzer.fuzz([0.5, 1, "demo_string", random_valid_grammar_string], 10000)

    assert True


@pytest.mark.skipif(False, reason="Not skiped!")
def test_map_range() -> None:
    logger.info("Start of test_map_range() test.")
    param_set: list[list]
    result: dict

    param_set = mutational_fuzzer.fuzz([0.0, 0.0, 0.0, 0.0, 0.0], 100000)
    result = param_runner.run(map_range, param_set)

    if result["failed_tests"] != 0:
        param_set = mutational_fuzzer.fuzz_failed(result, 20)
        result = param_runner.run(map_range, param_set)

    logger.info("test_map_range() test finished.")

    assert result["failed_tests"] == 0


@pytest.mark.skipif(False, reason="Not skiped!")
def test_hass_to_lox() -> None:
    logger.info("Start of test_hass_to_lox() test.")
    param_set: list[list]
    result: dict

    param_set = mutational_fuzzer.fuzz([0.0], 100000)
    result = param_runner.run(hass_to_lox, param_set)

    if result["failed_tests"] != 0:
        param_set = mutational_fuzzer.fuzz_failed(result, 20)
        result = param_runner.run(hass_to_lox, param_set)

    logger.info("test_hass_to_lox() test finished.")

    assert result["failed_tests"] == 0


@pytest.mark.skipif(False, reason="Not skiped!")
def test_lox_to_hass() -> None:
    logger.info("Start of test_lox_to_hass() test.")
    param_set: list[list]
    result: dict

    param_set = mutational_fuzzer.fuzz([0.0], 100000)
    result = param_runner.run(lox_to_hass, param_set)

    if result["failed_tests"] != 0:
        param_set = mutational_fuzzer.fuzz_failed(result, 20)
        result = param_runner.run(lox_to_hass, param_set)

    logger.info("test_lox_to_hass() test finished.")

    assert result["failed_tests"] == 0


@pytest.mark.skipif(False, reason="Not skiped!")
def test_lox2lox_mapped() -> None:
    logger.info("Start of test_lox2lox_mapped() test.")
    param_set: list[list]
    result: dict

    param_set = mutational_fuzzer.fuzz([0.0, 0.0, 0.0], 100000)
    result = param_runner.run(lox2lox_mapped, param_set)

    if result["failed_tests"] != 0:
        param_set = mutational_fuzzer.fuzz_failed(result, 20)
        result = param_runner.run(lox2lox_mapped, param_set)

    logger.info("test_lox2lox_mapped() test finished.")

    assert result["failed_tests"] == 0


@pytest.mark.skipif(False, reason="Not skiped!")
def test_lox2hass_mapped() -> None:
    logger.info("Start of test_lox2hass_mapped() test.")
    param_set: list[list]
    result: dict

    param_set = mutational_fuzzer.fuzz([0.0, 0.0, 0.0], 100000)
    result = param_runner.run(lox2hass_mapped, param_set)

    if result["failed_tests"] != 0:
        param_set = mutational_fuzzer.fuzz_failed(result, 20)
        result = param_runner.run(lox2hass_mapped, param_set)

    logger.info("test_lox2hass_mapped() test finished.")

    assert result["failed_tests"] == 0


@pytest.mark.skipif(False, reason="Not skiped!")
def test_to_hass_color_temp() -> None:
    logger.info("Start of test_to_hass_color_temp() test.")
    param_set: list[list]
    result: dict

    param_set = mutational_fuzzer.fuzz([0.0], 100000)
    result = param_runner.run(to_hass_color_temp, param_set)

    if result["failed_tests"] != 0:
        param_set = mutational_fuzzer.fuzz_failed(result, 20)
        result = param_runner.run(to_hass_color_temp, param_set)

    logger.info("test_to_hass_color_temp() test finished.")

    assert result["failed_tests"] == 0


@pytest.mark.skipif(False, reason="Not skiped!")
def test_to_loxone_color_temp() -> None:
    logger.info("Start of test_to_loxone_color_temp() test.")
    param_set: list[list]
    result: dict

    param_set = mutational_fuzzer.fuzz([0.0], 100000)
    result = param_runner.run(to_loxone_color_temp, param_set)

    if result["failed_tests"] != 0:
        param_set = mutational_fuzzer.fuzz_failed(result, 20)
        result = param_runner.run(to_loxone_color_temp, param_set)

    logger.info("test_to_loxone_color_temp() test finished.")

    assert result["failed_tests"] == 0


@pytest.mark.skipif(False, reason="Not skiped!")
def test_get_miniserver_type() -> None:
    logger.info("Start of test_get_miniserver_type() test.")
    param_set: list[list]
    result: dict

    param_set = mutational_fuzzer.fuzz([0], 100000)
    result = param_runner.run(get_miniserver_type, param_set)

    if result["failed_tests"] != 0:
        param_set = mutational_fuzzer.fuzz_failed(result, 20)
        result = param_runner.run(get_miniserver_type, param_set)

    logger.info("test_get_miniserver_type() test finished.")

    assert result["failed_tests"] == 0
