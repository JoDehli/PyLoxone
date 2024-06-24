import logging
import inspect
import coverage
from typing import Callable, List

from custom_components.test.fuzzing.fuzzer_utils.Runner import Runner
from custom_components.test.fuzzing.fuzzer_utils.fuzzer_tools.Seed import Seed, SeedManager


class GreyBoxRunner(Runner):
    """Greybox runner class, inherits from the abstract runner class."""

    __logger = None
    __seed_manager = None

    def __init__(self):
        """constructor"""
        self.__logger = logging.getLogger(__name__)
        self.__seed_manager = SeedManager()

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
        cov = coverage.Coverage(branch=True)

        sig = inspect.signature(function)
        num_params = len(sig.parameters)
        self.__logger.debug(f"The given functions needs {str(num_params)} parameters")

        test_results = {
            "passed_tests": 0,
            "failed_tests": 0,
        }

        for generation in range(0, amount_runs):
            seed = self.__seed_manager.select_seed(seed_population)
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

            data = cov.get_data()
            filename = next(iter(data.measured_files()))
            branches_covered = data.arcs(filename)
            
            new_branches = set(branches_covered) - coverages_seen
            coverages_seen.update(branches_covered)
            
            if new_branches:
                self.__logger.debug(f"Newly Covered Branches: {new_branches}")
                print(f"Test {generation}: Newly Covered Branches: {new_branches}")

  
        return test_results