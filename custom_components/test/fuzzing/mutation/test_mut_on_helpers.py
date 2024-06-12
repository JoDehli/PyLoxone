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
from custom_components.test.fuzzing.fuzzer_utils.grammars.grammar_ipv4 import grammar_ipv4
from custom_components.test.fuzzing.fuzzer_utils.ParamRunner import ParamRunner


_logger = logging.getLogger(__name__)

_mutational_fuzzer: MutationalFuzzer = MutationalFuzzer()
_grammar_fuzzer: GrammarFuzzer = GrammarFuzzer()
_param_runner: ParamRunner = ParamRunner()


def test_demo_get_param_set() -> None:
    # get a list of valid grammar outputs
    full_grammar_cov: list = _grammar_fuzzer.fuzz_grammar_coverage(
        grammar_ipv4, "<IPv4>"
    )
    # choose randomly on value
    random_valid_grammar_string = random.choice(full_grammar_cov)

    # If the grammar value should be an int or float, you have to cast the string first.
    # Get the param_set.
    _mutational_fuzzer.fuzz([0.5, 1, "demo_string", random_valid_grammar_string], 10000)

    assert True


def test_map_range() -> None:
    _logger.info("Start of test_map_range() test.")
    param_set: list[list] = _mutational_fuzzer.fuzz([0.5, 0.5, 12.3, 123.234, 0.0], 1000)
    param_set = _param_runner.limit_param_set(param_set, 50000)
    result: list = _param_runner.run(map_range, param_set)
    _logger.info("test_map_range() test finished.")

    assert result[1] == 0
