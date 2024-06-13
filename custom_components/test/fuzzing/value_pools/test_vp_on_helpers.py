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
from custom_components.test.fuzzing.fuzzer_utils.ValuePoolFuzzer import ValuePoolFuzzer
from custom_components.test.fuzzing.fuzzer_utils.ParamRunner import ParamRunner


logger = logging.getLogger(__name__)

value_pool_fuzzer = ValuePoolFuzzer()
param_runner = ParamRunner()


def test_map_range() -> None:
    logger.info("Start of map_range() test.")
    param_set = value_pool_fuzzer.fuzz(
        5, ["FLOAT", "FLOAT", "FLOAT", "FLOAT", "FLOAT"], 3
    )
    param_set = param_runner.limit_param_set(param_set, 50000)
    result = param_runner.run(map_range, param_set)
    logger.info("map_range() test finished.")

    assert result["failed_tests"] == 0


@pytest.mark.timeout(300)
def test_hass_to_lox() -> None:
    logger.info("Start of hass_to_lox() test.")
    param_set = value_pool_fuzzer.fuzz(1, ["FLOAT"], 1)
    result = param_runner.run(hass_to_lox, param_set)
    logger.info("hass_to_lox() test finished.")

    assert result["failed_tests"] == 0


@pytest.mark.timeout(300)
def test_lox_to_hass() -> None:
    logger.info("Start of lox_to_hass() test.")
    param_set = value_pool_fuzzer.fuzz(1, ["FLOAT"], 1)
    result = param_runner.run(lox_to_hass, param_set)
    logger.info("lox_to_hass() test finished.")

    assert result["failed_tests"] == 0


@pytest.mark.timeout(300)
def test_lox2lox_mapped() -> None:
    logger.info("Start of lox2lox_mapped() test.")
    param_set = value_pool_fuzzer.fuzz(3, ["FLOAT", "FLOAT", "FLOAT"], 2)
    result = param_runner.run(lox2lox_mapped, param_set)
    logger.info("lox2lox_mapped() test finished.")

    assert result["failed_tests"] == 0


@pytest.mark.timeout(300)
def test_lox2hass_mapped() -> None:
    logger.info("Start of lox2hass_mapped() test.")
    param_set = value_pool_fuzzer.fuzz(3, ["FLOAT", "FLOAT", "FLOAT"], 2)
    result = param_runner.run(lox2hass_mapped, param_set)
    logger.info("lox2hass_mapped() test finished.")

    assert result["failed_tests"] == 0


@pytest.mark.timeout(300)
def test_to_hass_color_temp() -> None:
    logger.info("Start of to_hass_color_temp() test.")
    param_set = value_pool_fuzzer.fuzz(1, ["FLOAT"], 1)
    result = param_runner.run(to_hass_color_temp, param_set)
    logger.info("to_hass_color_temp() test finished.")

    assert result["failed_tests"] == 0


@pytest.mark.timeout(300)
def test_to_loxone_color_temp() -> None:
    logger.info("Start of to_loxone_color_temp() test.")
    param_set = value_pool_fuzzer.fuzz(1, ["FLOAT"], 1)
    result = param_runner.run(to_loxone_color_temp, param_set)
    logger.info("to_loxone_color_temp() test finished.")

    assert result["failed_tests"] == 0


@pytest.mark.timeout(300)
def test_get_room_name_from_room_uuid() -> None:
    logger.info("Start of get_room_name_from_room_uuid() test.")
    param_set = value_pool_fuzzer.fuzz(2, ["DICT", "STRING"], 2)
    result = param_runner.run(get_room_name_from_room_uuid, param_set)
    logger.info("get_room_name_from_room_uuid() test finished.")

    assert result["failed_tests"] == 0


@pytest.mark.timeout(300)
def test_get_cat_name_from_cat_uuid() -> None:
    logger.info("Start of get_cat_name_from_cat_uuid() test.")
    param_set = value_pool_fuzzer.fuzz(2, ["DICT", "STRING"], 2)
    result = param_runner.run(get_cat_name_from_cat_uuid, param_set)
    logger.info("get_cat_name_from_cat_uuid() test finished.")

    assert result["failed_tests"] == 0


@pytest.mark.timeout(300)
def test_add_room_and_cat_to_value_values() -> None:
    logger.info("Start of add_room_and_cat_to_value_values() test.")
    param_set = value_pool_fuzzer.fuzz(2, ["DICT", "DICT"], 2)
    result = param_runner.run(add_room_and_cat_to_value_values, param_set)
    logger.info("add_room_and_cat_to_value_values() test finished.")

    assert result["failed_tests"] == 0


@pytest.mark.timeout(300)
def test_get_miniserver_type() -> None:
    logger.info("Start of get_miniserver_type() test.")
    param_set = value_pool_fuzzer.fuzz(1, ["INT"], 1)
    result = param_runner.run(get_miniserver_type, param_set)
    logger.info("get_miniserver_type() test finished.")

    assert result["failed_tests"] == 0


@pytest.mark.timeout(300)
@pytest.mark.skip(reason="No meaningful dict.")
def test_get_all() -> None:
    logger.info("Start of get_all() test.")
    param_set = value_pool_fuzzer.fuzz(2, ["DICT", "STRING"], 2)
    result = param_runner.run(get_all, param_set)
    logger.info("get_all() test finished.")

    assert result["failed_tests"] == 0
