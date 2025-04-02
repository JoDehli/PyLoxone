import logging
from typing import List, Tuple, Type, Any, Callable

from custom_components.test.fuzzing.fuzzer_utils.Runner import Runner

class GeneratorRunner(Runner):
    """Generator runner class, inherits from the abstract runner class."""

    def __init__(self):
        """Constructor for GeneratorRunner."""
        self._logger = logging.getLogger(__name__)

    def run(self, cls: Type, sequences: List[List[Tuple[str, Tuple[Any]]]]) -> List[int]:
        """
        Run the generated sequences on the given class.

        :param cls: The class on which the sequences will be run.
        :type cls: Type
        :param sequences: List of method sequences with parameters to be executed.
        :type sequences: List[List[Tuple[str, Tuple[Any]]]]
        :return: List containing the number of passed and failed tests.
        :rtype: List[int]
        """
        num_passed_tests: int = 0
        num_failed_tests: int = 0

        for sequence in sequences:
            sequence: List[Tuple[str, Tuple[Any]]]
            failed_test: bool = False
            err: Exception = None
            method_name: str
            param_set: Tuple[Any]
            method_name, param_set = sequence[0]
            if method_name == '__init__':
                instance = cls(*param_set)  # Initialize the Class with the intended parameters for __init__
                sequence = sequence[1:]  # Remove __init__ method from the sequence as we have already called it
            else:
                instance = cls()  # Create an instance of the class where the __init__ method does not require parameters
            for method_name, param_set in sequence:
                method: Callable = getattr(instance, method_name)
                num_params: int = len(param_set)
                self._logger.info(f"Running {method_name} with {num_params} parameters")

                try:
                    method(*param_set)  # Run the method with the given parameters
                except Exception as e:
                    e: Exception
                    err = e
                    failed_test = True
                    break 
            
            if not failed_test:
                self._logger.info(f"Test passed with sequence: {sequence}")
                num_passed_tests += 1
            else:
                self._logger.error(f"Test failed with sequence: {sequence}. Exception: {err}")
                num_failed_tests += 1

        return [num_passed_tests, num_failed_tests]
