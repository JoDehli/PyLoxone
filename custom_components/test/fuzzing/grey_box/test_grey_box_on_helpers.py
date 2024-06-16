from custom_components.test.fuzzing.fuzzer_utils.GreyBoxFuzzer import GreyBoxFuzzer
from custom_components.test.fuzzing.fuzzer_utils.fuzzer_tools.Seed import SeedManager, Seed
from custom_components.test.fuzzing.fuzzer_utils.fuzzer_tools.DataTypeCreator import DataTypeCreator

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


seed_manager = SeedManager()
grey_box_fuzzer = GreyBoxFuzzer()

# seed specification

seed_template = ["STRING"]
seed_specification = [4]
amount_seeds = 10

# create a population 

#seed_population = seed_manager.create_random_seed_population(seed_template, 3)
seed_population = seed_manager.create_specific_seed_population(seed_template,seed_specification,amount_seeds)

# Print seeds in population
for i in seed_population:
    print(i.seed_values)


grey_box_fuzzer.fuzz(seed_population, seed_template, crashme,10)
