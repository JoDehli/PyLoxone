from custom_components.test.fuzzing.fuzzer_utils.Fuzzer import Fuzzer
from custom_components.test.fuzzing.fuzzer_utils.fuzzer_tools.Seed import Seed
from typing import Callable, List

class GreyBoxFuzzer(Fuzzer):
    """GreyBox fuzzer class, inherits from the abstract fuzzer class."""

    def __init__(self):
        """initialize GreyBoxFuzzer"""
        print("Initialize GreyBoxFuzzer")

    def fuzz(self, seed_population: List[Seed], seed_template: list, function: Callable, rounds: int = 1):
        """The function returns a list of the number of passed and failed tests.
        The seed is changed randomly in any number of rounds (defined by rounds).

        :param seed_template: The seed_template is a list of input types for the function.
                              The entries must correspond to the valid function parameters of the function to be tested.
                              e.g.: ["INT", "FLOAT", "STRING", "BOOLEAN"]
        :type seed_template: list
        :param function: The function to test
        :type function: Callable
        :param rounds: SSpecifies how often the function should be tested with different inputs. The default is 1.
        :type rounds: int

        :return: Returns a list indicating how many tests were successful and how many failed.
        :rtype: list
        """
        for seed in seed_population:
            print(seed.seed_values)
        print("Fuzzing...")



