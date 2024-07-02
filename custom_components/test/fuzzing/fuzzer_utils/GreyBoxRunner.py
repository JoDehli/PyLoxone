import logging
import inspect
import coverage
import hashlib
import random
from typing import Callable, List

from custom_components.test.fuzzing.fuzzer_utils.Runner import Runner
from custom_components.test.fuzzing.fuzzer_utils.fuzzer_tools.Seed import Seed, SeedManager
from custom_components.test.fuzzing.fuzzer_utils.fuzzer_tools.Mutator import Mutator


class GreyBoxRunner(Runner):
    """Greybox runner class, inherits from the abstract runner class."""

    __logger = None
    __seed_manager = None
    __mutator = None
    path_dict = {}

    def __init__(self):
        """constructor"""
        self.__logger = logging.getLogger(__name__)
        self.__seed_manager = SeedManager()
        self.__mutator = Mutator()

    def run(self, function: Callable, seed_population: List[Seed], amount_runs: int = 10000) -> list:
        """Executes all transferred parameter sets for the transferred function.

        :param function: The passed function which is to be fuzzed.
        :type function: Callable

        :param seed_population: A list with seeds. A seed is a set of parameters.
        :type seed_population: list

        :param amount_runs: The number of times the function is to be tested.
        :param amount_runs: int 

        :return: Returns a dict with 2 keys,
                 the key 'passed_tests' contains the number of passed tests,
                 the key 'failed_tests' contains the number of failed tests.
        :rtype: dict
        """
        path_dict = {}
        path_counter = 0

        sig = inspect.signature(function)
        num_params = len(sig.parameters)
        self.__logger.debug(f"The given functions needs {str(num_params)} parameters")

        test_results = {
            "passed_tests": 0,
            "failed_tests": 0,
        }

        for generation in range(0, amount_runs):
            # get seed for the test
            seed = self.__seed_manager.select_seed(seed_population)

            # Mutate seed values
            self.__mutator.mutate_grey_box_fuzzer(seed)

            cov = coverage.Coverage(branch=True)
            cov.start()
            try:
                function(*seed.seed_values)
                cov.stop()
                cov.save()
                test_results["passed_tests"] += 1
                self.__logger.debug(f"Test {generation} passed with parameters: {seed.seed_values}")
            except Exception as e:
                cov.stop()
                cov.save()
                test_results["failed_tests"] += 1
                self.__logger.error(f"Test {generation} failed with parameters: {seed.seed_values}.")
                self.__logger.error(f"Exception: {e}")

            # check path coverage
            data = cov.get_data()
            filename = next(iter(data.measured_files()))
            path_covered = data.arcs(filename)

            # Create hash of path
            ###################print(f"path: {path_covered}")
            hashed_path = self.__hash_md5(str(path_covered))
            ###################print(f"Hashed path: {hashed_path}")
            
            # Check if a new path was covered
            if hashed_path not in self.path_dict:
                self.__logger.debug(f"Newly covered pathes: {path_covered}")
                #print(f"Test {generation}, seed_value: {seed.seed_values}, Newly covered pathes: {path_covered}")
                seed_population.append(seed)
                path_counter += 1


            # store hash in path_dict
            path_dict = self.__store_hashed_path(hashed_path, path_dict)
            
            # Adjust energy of seed
            ###################print(f"Energy before: {seed.energy}")
            self.__seed_manager.adjust_energy(seed, self.path_dict, hashed_path)
            ###################print(f"Energy after: {seed.energy}\n")

            

        #print("\n#####  Hashed pathes  #####\n")    
        #print(f"path_dict: {self.path_dict}")
        ###################print("\n#####  Covert pathes  #####\n")
        self.__logger.debug("\n#####  Covert pathes  #####\n")
        ###################print(f"In total there were {path_counter} pathes discovered")
        self.__logger.debug(f"In total there were {path_counter} pathes discovered")

        print("Population")
        for s in seed_population:
            print(f"{s.seed_values}")
  
        return test_results
    
    def __hash_md5(self, path_covered: str) -> str:
        md5_hash = hashlib.md5()
        md5_hash.update(path_covered.encode('utf-8'))
        return md5_hash.hexdigest()
    
    def __store_hashed_path(self, hashed_path: str, path_dict: dict) -> dict:
        if hashed_path in self.path_dict:
            self.path_dict[hashed_path] += 1
        else:
            self.path_dict[hashed_path] = 1
        
        return path_dict





