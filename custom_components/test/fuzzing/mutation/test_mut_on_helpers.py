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
    get_room_name_from_room_uuid,
    get_cat_name_from_cat_uuid,
    add_room_and_cat_to_value_values,
    get_miniserver_type,
    get_all,
)
from custom_components.test.fuzzing.fuzzer_utils.MutationalFuzzer import (
    MutationalFuzzer,
)
from custom_components.test.fuzzing.fuzzer_utils.GrammarFuzzer import GrammarFuzzer
from custom_components.test.fuzzing.fuzzer_utils.grammars.grammar_ipv4 import (
    grammar_ipv4,
)
from custom_components.test.fuzzing.fuzzer_utils.ParamRunner import ParamRunner


logger = logging.getLogger(__name__)

mutational_fuzzer: MutationalFuzzer = MutationalFuzzer()
grammar_fuzzer: GrammarFuzzer = GrammarFuzzer()
param_runner: ParamRunner = ParamRunner()

@pytest.mark.skip(reason="Only dummy test case.")
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
