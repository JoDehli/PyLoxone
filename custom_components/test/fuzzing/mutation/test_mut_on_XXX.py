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
    get_room_name_from_room_uuid,
    get_cat_name_from_cat_uuid,
    add_room_and_cat_to_value_values,
    get_miniserver_type,
    get_all,
)
from custom_components.test.fuzzing.fuzzer_utils.MutationalFuzzer import (
    MutationalFuzzer,
)
from custom_components.test.fuzzing.fuzzer_utils.ParamRunner import ParamRunner


logger = logging.getLogger(__name__)

mutational_fuzzer = MutationalFuzzer()
param_runner = ParamRunner()


def test_dummy() -> None:
    logger.info("Start of test_dummy() test.")
    param_set = mutational_fuzzer.fuzz([0.5, 0.5, 12, "xxs", 0], 100)
    param_set = param_runner.limit_param_set(param_set, 50000)
    result = param_runner.run(map_range, param_set)
    logger.info("test_dummy() test finished.")

    assert result[1] == 0
