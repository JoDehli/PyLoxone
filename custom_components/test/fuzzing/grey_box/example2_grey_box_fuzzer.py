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

# Function to test the grey box fuzzer
def crashme(s: str) -> None:
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


grey_box_fuzzer = GreyBoxFuzzer()
grey_box_runner = GreyBoxRunner()

# seed specification

amount_seeds = 10
seed_template = ["STRING"]
seed_specification = [4]


# create a population with fuzzer
seed_population = grey_box_fuzzer.fuzz(seed_template, seed_specification, 10)

# Print seeds in population
print("#####  Population  #####")
for i in seed_population:
    print(i.seed_values)

print("\n#####  Execute Tests  #####\n")

test_results = grey_box_runner.run(crashme, seed_population, 10)


print("\n#####  Test restults  #####\n")
print(f"Tests passed: {test_results['passed_tests']}")
print(f"Tests failed: {test_results['failed_tests']}")
