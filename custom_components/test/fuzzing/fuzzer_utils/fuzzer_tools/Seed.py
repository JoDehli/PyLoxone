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

    __value_pool_fuzzer = ValuePoolFuzzer()
    __param_runner = ParamRunner()
    __data_type_creator = DataTypeCreator()

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
        param_combi = random.randint(1, len(seed_template))
        param_set = self.__value_pool_fuzzer.fuzz(len(seed_template),seed_template, param_combi)
        param_set = self.__param_runner.limit_param_set(param_set, amount_seeds)

        seed_population = []
        for param in param_set:
            seed = Seed(energy=1, seed_values=param)
            seed_population.append(seed)
        
        return seed_population

    def create_specific_seed_population(self, seed_template: list, seed_specification: list, amount_seeds: int) -> List[Seed]:
        """Returns a population of seeds with specific values based on the seed template and seed specifiction.

        This function takes two list 'seed_template' and 'seed_specification' and creates seeds. 
        The number of specific seeds is specified by 'amount_seeds'. A list of the random seeds is returned.

        :param seed_template: A list of the data types of the seeds.
                              Supported data types: "INT", "UINT", "FLOAT", "STRING", "BOOL", "BYTE", "LIST", "DICT", "DATE", 
                              E.g.: ["STRING", "INT", "INT"]
        :type seed_template: list

        :param seed_specification: A list that provides the number of digits for each data type in seed_template.
                                   If a random data type is to be initialised anyway, this must be marked with an 'r'.
                                   E.g.: [5, 2, 'r']
        :type seed_specification: list

        :param amount_seeds: Amount of specific seeds which will be created.
        :type amount_seeds: int

        :return: Returns a list of specific seed objects.
        :rtype: list
        """
        param_combi = random.randint(1, len(seed_template))

        # Throw exception if seed_specification and seed_template aren't the same length
        if len(seed_template) != len(seed_specification):
            raise ValueError("Length of seed_template and seed_specification must be the same length.")

        seed_population = []

        for _ in range(amount_seeds):
            param_set = []
            for seed_spec, data_type in zip(seed_specification, seed_template):
                if data_type == "INT":
                    param_set.append(self.__data_type_creator.create_int(seed_spec))
                elif data_type == "UINT":
                    param_set.append(self.__data_type_creator.create_uint(seed_spec))
                elif data_type == "FLOAT":
                    print("create_float")
                elif data_type == "STRING":
                    rand_val = random.randint(0,1)
                    if rand_val == 0:
                        param_set.append(self.__data_type_creator.create_string_only_letters(seed_spec))
                    elif rand_val == 1: 
                        param_set.append(self.__data_type_creator.create_string_special_characters(seed_spec))
                elif data_type == "BOOL":
                    param_set.append(random.choice([True, False]))
                elif data_type == "BYTE":
                    print("create_byte")
                elif data_type == "LIST":
                    print("create_list")
                elif data_type == "DICT":
                    print("create_dict")
                elif data_type == "DATE":
                    print("create_date")
            
            seed = Seed(1, param_set)
            seed_population.append(seed)

        return seed_population

                        



