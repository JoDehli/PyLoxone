import pytest
import logging


from value_pool import ValuePool
from PyLoxone.custom_components.loxone.helpers import map_range


logger = logging.getLogger(__name__)

value_pool = ValuePool()


@pytest.mark.parametrize(
    "value, in_min, in_max, out_min, out_max",
    value_pool.get_all_combinations_of_pool(value_pool.UINT_POOL, 5),
)
def test_map_range(value, in_min, in_max, out_min, out_max):
    passed = True
    try:
        result = map_range(value, in_min, in_max, out_min, out_max)
        logger.info(
            "Passed for parameters: value: "
            + str(value)
            + " in_min: "
            + str(in_min)
            + " in_max:"
            + str(in_max)
            + " out_min: "
            + str(out_min)
            + " out_max: "
            + str(out_max)
            + " result: "
            + str(result)
        )
    except Exception as error:
        passed = False
        logger.error(
            "Failed for parameters: value: "
            + str(value)
            + " in_min: "
            + str(in_min)
            + " in_max:"
            + str(in_max)
            + " out_min: "
            + str(out_min)
            + " out_max: "
            + str(out_max)
        )
        logger.error(error)
        passed = False
    assert passed == True
