from custom_components.test.fuzzing.fuzzer_utils.fuzzer_tools.Seed import Seed
from custom_components.test.fuzzing.fuzzer_utils.MutationalFuzzer import MutationalBlackBoxFuzzer
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
        seed.seed_values[random_index] = self.__mutationalFuzzer.fuzz([seed_value],2)[1][0]

        print(seed.seed_values)