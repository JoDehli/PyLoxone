import logging
import inspect
import coverage
import hashlib
from typing import Callable, List

from custom_components.test.fuzzing.fuzzer_utils.Runner import Runner
from custom_components.test.fuzzing.fuzzer_utils.fuzzer_tools.Seed import Seed, SeedManager
from custom_components.test.fuzzing.fuzzer_utils.fuzzer_tools.Mutator import Mutator


class GreyBoxRunner(Runner):
    """Greybox runner class, inherits from the abstract runner class."""

    __logger = None
    __seed_manager = None
    __mutator = None
    __branch_dict = {}

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
        coverages_seen = set()
        branch_counter = 0

        sig = inspect.signature(function)
        num_params = len(sig.parameters)
        self.__logger.debug(f"The given functions needs {str(num_params)} parameters")

        test_results = {
            "passed_tests": 0,
            "failed_tests": 0,
        }

        for generation in range(0, amount_runs):
            seed = self.__seed_manager.select_seed(seed_population)
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

            # check branch coverage
            data = cov.get_data()
            filename = next(iter(data.measured_files()))
            branch_covered = data.arcs(filename)
            new_branches = set(branch_covered) - coverages_seen
            coverages_seen.update(branch_covered)
            
            if new_branches:
                self.__logger.debug(f"Newly covered branches: {new_branches}")
                print(f"Test {generation}, seed_value: {seed.seed_values}, Newly covered branches: {new_branches}")
                branch_counter += 1
            else:
                print(f"Test {generation}, seed_value: {seed.seed_values}, No newly covered branches")

            # Create hash and store it in dict
            hashed_branch = self.__hash_md5(str(branch_covered))
            print(f"Hashed branch: {hashed_branch}")
            self.__store_hashed_branch(hashed_branch)

            # Adjust energy of seed
            print(f"Energy before: {seed.energy}")
            self.__seed_manager.adjust_energy(seed, self.__branch_dict, hashed_branch)
            print(f"Energy after: {seed.energy}\n")

            # Mutate seed values
            self.__mutator.mutate_grey_box_fuzzer(seed)

        print("\n#####  Hashed branches  #####\n")    
        print(f"Branch_dict: {self.__branch_dict}")
        print("\n#####  Covert branches  #####\n")
        print(f"In total there were {branch_counter} branches discovered ")
  
        return test_results
    
    def __hash_md5(self, branch_covered: str) -> str:
        md5_hash = hashlib.md5()
        md5_hash.update(branch_covered.encode('utf-8'))
        return md5_hash.hexdigest()
    
    def __store_hashed_branch(self, hashed_branch: str):
        if hashed_branch in self.__branch_dict:
            self.__branch_dict[hashed_branch] += 1
        else:
            self.__branch_dict[hashed_branch] = 1
