from typing import List
import random
import copy

class Seed:

    energy = 0
    seed_values = []

    def __init__(self, energy: int = 0, seed_values: list = []):
        """initialize PowerSchedule"""
        self.energy = energy
        self.seed_values = seed_values


class SeedManager:
    __power_energy = 2

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
        normalized_energy = self.get_normalized_energy(seed_population)
        random_value = random.uniform(0,1)
        for index, normalized_energy_val in enumerate(normalized_energy):
            if random_value <= normalized_energy_val:
                seed = copy.deepcopy(seed_population[index])
                break

        return seed
    
    def adjust_energy(self, seed: Seed, branch_dict: dict, hashed_branch: str):
        """Adjusts the energy of a given seed. 

        This function changes the energy of a seed based on how many times the branch was executed.
        The formula for the adustment is: e = 1 / number_path_exercised
        The number_path_exercised is the number of the how many times the path was seen in total.

        :param seed: A seed with a value and energy attribute.
        :type seed: Seed 

        :param branch_dict: A dictionary with hashes of the paths and a value of how many times the path was exercised.
        :type branch_dict: dict

        :param hashed_branch: A hash of a path.
        :type hashed_branch: str

        :return: Returns a single seed.
        :rtype: Seed
        """
        number_path_exercised = branch_dict[hashed_branch]
        seed.energy = 1 / (number_path_exercised ** self.__power_energy)

    def get_normalized_energy(self, seed_population: List[Seed]) -> list:
        total_energy = 0
        for seed in seed_population:
            total_energy += seed.energy

        normalized_energy = []

        for index, seed in enumerate(seed_population):
            if index == 0:
                normalized_energy.append(seed.energy / total_energy)
            else:
                normalized_energy.append(normalized_energy[index-1] + (seed.energy / total_energy))

        return normalized_energy
    



                        



