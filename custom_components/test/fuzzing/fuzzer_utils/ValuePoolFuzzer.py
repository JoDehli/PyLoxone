from Fuzzer import Fuzzer


class ValuePoolFuzzer(Fuzzer):
    """Value pool fuzzer class, inherits from the abstract fuzzer class."""

    def __int__(self):
        """constructor"""
        pass

    def fuzz(
        self, param_nr: int = 1, types: list = ["INT"], param_combi: int = 1
    ) -> list:
        """Generates an individual value pool for fuzzing based on the parameters. A list of lists is returned.

        TODO: @jonathanheitzmann implement function
        TODO: @jonathanheitzmann specify valid types
        TODO: @jonathanheitzmann add comments and update UML if necessary

        :param param_nr: Number of parameters of the function to be fuzzed. Each list in the return list contains a corresponding number of entries.
        :type param_nr: int
        :param types: A list of required data types is transferred. The list must be the same length as the number of parameters specified under param_nr for the function to be fuzzed. e.g. ["int", "float", "char"]
        :type types: list
        :param param_combi: param_combi can have a maximum of the number of parameters specified under param_nr. The user can specify whether he wants to have all combinations in his list (param_nr = param_combi) or e.g. only a 2-fold combination.
        :type param_combi: int

        :return: The value pool as list of lists.
        :rtype: list
        """

        dummy_list = [
            [-1, -1, 0],
            [-1, 0, 1],
            [-1, 1, -1],
            [0, -1, 0],
            [0, 0, 1],
            [0, 1, -1],
            [1, -1, 0],
            [1, 0, 1],
            [1, 1, -1],
        ]
        return dummy_list
