import logging
import inspect
from typing import List, Tuple, Type, Any
from custom_components.test.fuzzing.fuzzer_utils.Runner import Runner

class GeneratorRunner(Runner):
    """Generator runner class, inherits from the abstract runner class."""

    def __init__(self):
        """Constructor for GeneratorRunner."""
        pass

    def run(self, cls: Type, sequences: List[List[Tuple[str, List[Any]]]]) -> List[int]:
        """
        Run the generated sequences on the given class.

        :param cls: The class on which the sequences will be run.
        :type cls: Type
        :param sequences: List of method sequences with parameters to be executed.
        :type sequences: List[List[Tuple[str, List[Any]]]]
        :return: List containing the number of passed and failed tests.
        :rtype: List[int]
        """
        logger = logging.getLogger(__name__)
        passed_tests = 0
        failed_tests = 0

        for sequence in sequences:
            instance = cls()  # Create an instance of the class
            for method_name, param_set in sequence:
                method = getattr(instance, method_name)
                num_params = len(param_set)
                logger.info(f"Running {method_name} with {num_params} parameters")

                for params in param_set:
                    try:
                        method(*params)  # Run the method with the given parameters
                        logger.debug(f"Test passed with parameters: {params}")
                        passed_tests += 1
                    except Exception as e:
                        logger.error(f"Test failed with parameters: {params}. Exception: {e}")
                        failed_tests += 1

        return [passed_tests, failed_tests]
