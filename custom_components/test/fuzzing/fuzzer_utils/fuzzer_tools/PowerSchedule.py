from typing import List
from custom_components.test.fuzzing.fuzzer_utils.fuzzer_tools.Seed import Seed

class PowerSchedule:

    def __init__(self):
        """initialize PowerSchedule"""
        print("Initialize PowerSchedule")

    def assignEnergy(self, population: List[Seed]) -> None:
        """Assigns energy to seeds.

        This function takes a population of Seeds and assigns to every seed an energy of 1.

        :param population: List of type Seed.
        :type population: list
        """
        for seed in population:
            seed.energy = 1

    def normalizedEnergy(self, population: List[Seed]) -> None:
        """Normalize energy of all seeds.

        This function takes a population of Seeds and normalizes the energy by dividing the 
        energy of every seed through sum of all energy values.

        :param population: List of type Seed.
        :type population: list
        """

    def choose(self, population: List[Seed]) -> Seed:
        """Returns a seed that was selected based on the energy.

        This function takes a population of Seeds and returns and selects a Seed by the energy of the seed. 
        The higher the energy, the more likely it is that the seed will be selected.

        :param population: List of type Seed.
        :type population: list

        :return: Returns a seed.
        :rtype: Seed
        """