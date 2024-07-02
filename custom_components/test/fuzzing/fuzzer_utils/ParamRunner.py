import logging
import inspect
import random

from custom_components.test.fuzzing.fuzzer_utils.Runner import Runner


class ParamRunner(Runner):
    """Paramter runner class, inherits from the abstract runner class."""

    __logger = None

    def __init__(self):
        """constructor"""
        self.__logger = logging.getLogger(__name__)

    def run(self, function, param_set: list) -> dict:
        """Executes all transferred parameter sets for the transferred function.

        :param function: The passed function which is to be fuzzed.
        :type function: function
        :param param_set: The parameter set transferred from the fuzzer.
        :type param_set: list

        :return: Returns a dict with 3 keys,
                 the key 'passed_tests' contains the number of passed tests,
                 the key 'failed_tests' contains the number of failed tests,
                 and the last key 'failed_params' contains a dict with every failed param_set (compare example).
        :rtype: dict

        .. code-block:: python
            {
                "passed_tests": 10,
                "failed_tests": 1,
                "failed_params": {
                    "1": [1.0,2,"xxx"],
                    "2": [1.0,223,"demo"]
                }
            }
        """

        sig = inspect.signature(function)
        num_params = len(sig.parameters)
        self.__logger.debug(f"The given functions needs {str(num_params)} parameters")

        test_results = {
            "passed_tests": 0,
            "failed_tests": 0,
            "failed_params": {},
        }

        for index, param in enumerate(param_set):
            try:
                function(*param)
                test_results["passed_tests"] += 1
                self.__logger.debug(f"Test {index} passed with parameters: {param}")
            except Exception as e:
                test_results["failed_tests"] += 1
                test_results["failed_params"][str(index)] = param
                self.__logger.error(f"Test {index} failed with parameters: {param}.")
                self.__logger.error(f"Exception: {e}")

        if test_results["failed_tests"] > 0:
            self.__logger.error(
                "Summary: "
                + str(test_results["failed_tests"])
                + " of "
                + str(test_results["failed_tests"] + test_results["passed_tests"])
                + " param_sets failed for the function "
                + str(function.__name__)
            )
        else:
            self.__logger.info(
                "Summary: All "
                + str(test_results["passed_tests"])
                + " param_sets passed for the function "
                + str(function.__name__)
            )

        return test_results

    def limit_param_set(self, param_set: list, runs: int) -> list:
        """Generates a specific selection of an individual value pool. A list of lists is returned with a specified number of elements.

        :param param_set: The value pool as list of lists.
        :type param_nr: list
        :param runs: Number of elements selected from the value pool.
        :type types: int

        :return: A random selection of certain elements from the parameter set.
        :rtype: list
        """

        # Validate input parameters
        if not isinstance(param_set, list):
            self.__logger.error("Param_set must be of type list.")
            raise TypeError("Param_set must be of type list.")
        if len(param_set) == 0:
            self.__logger.error("Length of param_set must be greater then 0.")
            raise ValueError("Length of param_set must be greater then 0.")
        if not isinstance(runs, int) or runs <= 0:
            self.__logger.error(
                "Runs must be of type int and greater than 0. Parameter set is returned unchanged."
            )
            return param_set

        # Selection of random elements from param_set if the number of runs is smaller than the number of elements in param_set
        if runs > len(param_set):
            self.__logger.info(
                "Length of param_set is smaller than the value of runs. Returned param_set unchanged."
            )
            return param_set
        else:
            self.__logger.info(
                f"Decresed elements in param_set from {len(param_set)} to {runs}"
            )
            return random.sample(param_set, runs)
