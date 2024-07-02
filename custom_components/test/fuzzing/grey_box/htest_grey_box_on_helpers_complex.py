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
def complex_function(input_string: str) -> int:
    result = 0
    length = len(input_string)
    
    # Grundlegende Bedingung auf Länge
    if length > 10:
        result += 1
        if length > 20:
            result += 1
            if input_string.startswith("A"):
                result += 1
            if input_string.endswith("Z"):
                result += 1
    else:
        result -= 1

    # Bedingung auf spezifische Zeichen
    if 'a' in input_string:
        result += 2
        if input_string.count('a') > 3:
            result += 3
        if 'aaa' in input_string:
            result += 5
        else:
            result -= 1
    else:
        result -= 2

    # Schleifen und verschachtelte Bedingungen
    vowels = "aeiou"
    consonants = "bcdfghjklmnpqrstvwxyz"

    for i, char in enumerate(input_string):
        if char in vowels:
            result += 1
        elif char in consonants:
            result += 2
        else:
            result -= 1
        
        # Verschachtelte Schleifen
        for j in range(i, length):
            if input_string[j] == char:
                result += 1
            else:
                result -= 1
            
            # Noch eine Ebene der Verschachtelung
            if j % 2 == 0:
                result += 2
            else:
                result -= 2

    # Weitere komplexe Bedingungen
    if 'xyz' in input_string:
        result += 10
    if input_string.isdigit():
        result -= 10
    if input_string.isalpha():
        result += 20
    
    # Substrings und Indizes
    if "fuzz" in input_string:
        index = input_string.find("fuzz")
        if index % 2 == 0:
            result += 30
        else:
            result -= 30
    
    # Rückgabe des Ergebnisses
    return result



grey_box_fuzzer = GreyBoxFuzzer()
grey_box_runner = GreyBoxRunner()

# seed specification

amount_seeds = 10
seed_template = ["STRING"]
seed_specification = ['r']


# create a population with fuzzer
seed_population = grey_box_fuzzer.fuzz(seed_template, seed_specification, 100)

# Print seeds in population
print("#####  Population  #####")
for i in seed_population:
    print(i.seed_values)

print("\n#####  Execute Tests  #####\n")

test_results = grey_box_runner.run(complex_function, seed_population, 2000)

print("\n#####  Test restults  #####\n")
print(f"Tests passed: {test_results['passed_tests']}")
print(f"Tests failed: {test_results['failed_tests']}")

