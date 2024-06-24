from typing import List
from custom_components.test.fuzzing.fuzzer_utils.ValuePoolFuzzer import ValuePoolFuzzer
from custom_components.test.fuzzing.fuzzer_utils.ParamRunner import ParamRunner
from custom_components.test.fuzzing.fuzzer_utils.fuzzer_tools.DataTypeCreator import DataTypeCreator
import random

class Seed:

    energy = 0
    seed_values = []

    def __init__(self, energy: int = 0, seed_values: list = []):
        """initialize PowerSchedule"""
        self.energy = energy
        self.seed_values = seed_values


class SeedManager:
    counter = -1

    def __init__(self):
        """initialize PowerSchedule"""

    def select_seed(self, seed_population: List[Seed]) -> Seed:
        """Selects a seed based on their energy. 

        This function selects a seed. 
        The higher the energy of a seed, the more likely it is that a seed will be selected.

        :param seed_population: A list with seeds. A seed is a set of parameters.
        :type seed_population: list 

        :return: Returns a single seed.
        :rtype: Seed
        """
        self.counter += 1
        return seed_population[self.counter]


                        



