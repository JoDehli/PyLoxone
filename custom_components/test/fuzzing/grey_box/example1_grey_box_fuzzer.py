from custom_components.test.fuzzing.fuzzer_utils.GreyBoxFuzzer import GreyBoxFuzzer
from custom_components.test.fuzzing.fuzzer_utils.GreyBoxRunner import GreyBoxRunner
from custom_components.test.fuzzing.fuzzer_utils.fuzzer_tools.Seed import Seed

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

def path_coverage_function(f: float, s: str, i: int) -> str:
    if f > 0.0:
        if len(s) > 5:
            if i % 2 == 0:
                return "Path 1: f > 0.0, len(s) > 5, i is even"
            else:
                return "Path 2: f > 0.0, len(s) > 5, i is odd"
        else:
            if i % 2 == 0:
                return "Path 3: f > 0.0, len(s) <= 5, i is even"
            else:
                return "Path 4: f > 0.0, len(s) <= 5, i is odd"
    else:
        if len(s) > 5:
            if i % 2 == 0:
                return "Path 5: f <= 0.0, len(s) > 5, i is even"
            else:
                return "Path 6: f <= 0.0, len(s) > 5, i is odd"
        else:
            if i % 2 == 0:
                return "Path 7: f <= 0.0, len(s) <= 5, i is even"
            else:
                raise Exception()



grey_box_fuzzer = GreyBoxFuzzer()
grey_box_runner = GreyBoxRunner()

# seed specification

amount_seeds = 10
seed_template = ["FLOAT", "STRING", "INT"]
seed_specification = ['r','r','r']


# create a population with fuzzer
seed_population = grey_box_fuzzer.fuzz(seed_template, seed_specification, 10)

# Print seeds in population
print("#####  Population  #####")
for i in seed_population:
    print(i.seed_values)

print("\n#####  Execute Tests  #####\n")

test_results = grey_box_runner.run(path_coverage_function, seed_population, 2000)

print("\n#####  Test restults  #####\n")
print(f"Tests passed: {test_results['passed_tests']}")
print(f"Tests failed: {test_results['failed_tests']}")

