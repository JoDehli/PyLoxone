from custom_components.test.fuzzing.fuzzer_utils.Fuzzer import Fuzzer
from custom_components.test.fuzzing.fuzzer_utils.fuzzer_tools.Seed import Seed
from custom_components.test.fuzzing.fuzzer_utils.fuzzer_tools.DataTypeCreator import DataTypeCreator
from typing import List
import random

class GreyBoxFuzzer(Fuzzer):
    """GreyBox fuzzer class, inherits from the abstract fuzzer class."""

    __RANGE_RANDOM_STRING = 100
    __data_type_creator = DataTypeCreator()

    def __init__(self):
        """initialize GreyBoxFuzzer"""
        print("Initialize GreyBoxFuzzer")

    def fuzz(self, 
             seed_template: list,
             seed_specification: list = None,
             amount_seeds: int = 100) -> List[Seed]:
        """Returns a population of seeds with specific values based on the seed template and seed specifiction.
        
        This function takes two lists 'seed_template' and 'seed_specification' and creates seeds. 
        The number of seeds is specified by 'amount_seeds'. A list of the random seeds is returned.

        :param seed_template: The seed_template is a list of input types for the function.
                              The entries must correspond to the valid function parameters of the function to be tested.
                              Valid inputs are "INT", "FLOAT", "STRING" and "BOOLEAN".
                              e.g.: ["INT", "FLOAT", "STRING", "BOOLEAN"]
        :type seed_template: list

        :param seed_specification: A list that provides the number of digits for each data type in seed_template.
                                   If a random data type is to be initialised anyway, this must be marked with an 'r'.
                                   Defalault value ist random for every data type.
                                   E.g.: [5, 2, 'r']
        :type seed_specification: list

        :param amount_seeds: Amount of seeds which will be created.
        :type amount_seeds: int

        :return: Returns a list indicating how many tests were successful and how many failed.
        :rtype: list
        """

        # Throw exception if seed_specification and seed_template aren't the same length
        if len(seed_template) != len(seed_specification):
            raise ValueError("Length of seed_template and seed_specification must be the same length.")

        seed_population = []

        for _ in range(amount_seeds):
            param_set = []
            for seed_spec, data_type in zip(seed_specification, seed_template):
                if data_type == "INT":
                    if seed_spec == 'r':
                        param_set.append(self.__data_type_creator.create_int(seed_spec,True))
                    else:    
                        param_set.append(self.__data_type_creator.create_int(seed_spec,False))

                elif data_type == "FLOAT":
                    if seed_spec == 'r':
                        param_set.append(self.__data_type_creator.create_float(seed_spec,True))
                    else:
                        param_set.append(self.__data_type_creator.create_float(seed_spec,False))

                elif data_type == "STRING":
                    if seed_spec == 'r':
                        seed_spec = random.randint(1, self.__RANGE_RANDOM_STRING)
                    rand_val = random.randint(0,1)
                    if rand_val == 0:
                        param_set.append(self.__data_type_creator.create_string_only_letters(seed_spec))
                    elif rand_val == 1: 
                        param_set.append(self.__data_type_creator.create_string_special_characters(seed_spec))
                        
                elif data_type == "BOOL":
                    param_set.append(random.choice([True, False]))
            
            seed = Seed(1, param_set)
            seed_population.append(seed)

        return seed_population