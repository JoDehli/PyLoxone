from typing import List

class Seed:

    energy = 0
    seed_values = []

    def __init__(self, energy: int = 0, seed_values: list = []):
        """initialize PowerSchedule"""
        self.energy = energy
        self.seed_values = seed_values


class SeedManager:

    def __init__(self):
        """initialize PowerSchedule"""

    def create_random_seed_population(self, seed_template: list, amount_seeds: int) -> List[Seed]:
        """Returns a population of seeds with random values specified by the seed_template.

        This function takes a list 'seed_template' an creates random seeds based on the seed template.
        The number of random seeds is specified by 'amount_seeds'. A list of the random seeds is returned.

        :param seed_template: A list of the data types of the seeds.
        :type seed_template: list

        :param amount_seeds: Amount of random seeds which will be created.
        :type amount_seeds: int

        :return: Returns a list of random seed objects.
        :rtype: list
        """



