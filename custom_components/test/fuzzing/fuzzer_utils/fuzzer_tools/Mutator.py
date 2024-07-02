from custom_components.test.fuzzing.fuzzer_utils.fuzzer_tools.Seed import Seed
from custom_components.test.fuzzing.fuzzer_utils.MutationalFuzzer import MutationalBlackBoxFuzzer

from random import random
import random

class Mutator:

    __mutationalFuzzer = None

    def __init__(self):
        """initialize Mutator"""
        self.__mutationalFuzzer = MutationalBlackBoxFuzzer()

    def mutate_grey_box_fuzzer(self, seed: Seed):
        """Mutates one of the seed values.

        This function takes a seed and mutates one of the seed values of it.

        :param seed: A seed consists of a list of seed_values.
        :type seed: Seed
        """
        amount_values = len(seed.seed_values)
        random_index = random.choice(range(0,amount_values))
        seed_value = seed.seed_values[random_index]

        if isinstance(seed_value, str):
            seed.seed_values[random_index] = self.__mutate_string(seed_value)
        if isinstance(seed_value, int):
            seed.seed_values[random_index] = self.__mutate_int(seed_value)

    def __mutate_string(self, seed_value: str) -> str:
        """Mutates a string random.

        This function takes a string and applies different mutations on it.
        1. delete random char
        2. insert random char
        3. flip random char

        :param seed_value: A string which should be mutated.
        :type seed_value: str

        :return: Returns the mutated seed value.
        :rtype: str
        """
        random_val = random.choice([1, 2, 3])
        if random_val == 1:
            seed_value = self.__mutationalFuzzer.delete_random_char(seed_value)
        elif random_val == 2:
            seed_value = self.__mutationalFuzzer.insert_random_char(seed_value)
        elif random_val == 3:
            seed_value = self.__mutationalFuzzer.flip_random_char(seed_value)
        
        return seed_value
    
    def __mutate_int(self, seed_value: str) -> str:
        """Mutates an integer random.

        This function takes an integer and applies different mutations on it.
        1. delete random char
        2. insert random char
        3. flip random char

        :param seed_value: A string which should be mutated.
        :type seed_value: str

        :return: Returns the mutated seed value.
        :rtype: str
        """
        random_val = random.choice([1, 2, 3])
        if random_val == 1:
            seed_value = self.__mutationalFuzzer.delete_random_char(seed_value)
        elif random_val == 2:
            seed_value = self.__mutationalFuzzer.insert_random_char(seed_value)
        elif random_val == 3:
            seed_value = self.__mutationalFuzzer.flip_random_char(seed_value)
        
        return seed_value