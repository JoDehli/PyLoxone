import pytest
import logging
import random
import json

from custom_components.loxone.helpers import (
    map_range,
    hass_to_lox,
    lox_to_hass,
    lox2lox_mapped,
    lox2hass_mapped,
    to_hass_color_temp,
    to_loxone_color_temp,
    get_room_name_from_room_uuid,
    get_cat_name_from_cat_uuid,
    add_room_and_cat_to_value_values,
    get_miniserver_type,
    get_all,
)
from custom_components.test.fuzzing.fuzzer_utils.MutationalFuzzer import (
    MutationalBlackBoxFuzzer,
)
from custom_components.test.fuzzing.fuzzer_utils.GrammarFuzzer import GrammarFuzzer
from custom_components.test.fuzzing.fuzzer_utils.grammar_pool import (
    grammar_ipv4,
    grammar_controls_json,
)
from custom_components.test.fuzzing.fuzzer_utils.ParamRunner import ParamRunner


logger = logging.getLogger(__name__)

mutational_fuzzer: MutationalBlackBoxFuzzer = MutationalBlackBoxFuzzer()
grammar_fuzzer: GrammarFuzzer = GrammarFuzzer()
param_runner: ParamRunner = ParamRunner()


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


@pytest.mark.skipif(True, reason="Waiting for Grammar!")
@pytest.mark.timeout(300)
def test_get_room_name_from_room_uuid() -> None:
    assert True


@pytest.mark.skipif(True, reason="Waiting for Grammar!")
@pytest.mark.timeout(300)
def test_get_cat_name_from_cat_uuid() -> None:
    assert True


@pytest.mark.skipif(True, reason="Waiting for Grammar!")
@pytest.mark.timeout(300)
def test_add_room_and_cat_to_value_values() -> None:
    assert True


@pytest.mark.skipif(False, reason="Not skiped!")
def test_get_all() -> None:
    logger.info("Start of test_get_all() test.")
    param_set: list[list]
    result: dict

    # get a list of valid grammar outputs
    full_grammar_cov: list[str]
    full_grammar_cov = grammar_fuzzer.fuzz_grammar_coverage(
        grammar_controls_json, "<JSON>"
    )

    # choose randomly on grammar string
    random_valid_grammar_string: str
    random_valid_grammar_string = random.choice(full_grammar_cov)

    # mutate seed
    param_set = mutational_fuzzer.fuzz([random_valid_grammar_string, "a"], 100)

    # function under test needs a json object
    for set in param_set:
        # is param after mutation still a valid json?
        try:
            # Yes -> load as json
            set[0] = json.loads(set[0])
        except:
            # No -> use random default value from grammar
            logger.debug(
                f"{set[0]} is not longer a valid json, replaced it with value from grammar."
            )
            set[0] = json.loads(random.choice(full_grammar_cov))

    result = param_runner.run(get_all, param_set)

    logger.info("test_get_all() test finished.")

    assert result["failed_tests"] == 0
