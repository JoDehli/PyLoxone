import itertools
import logging


from custom_components.test.fuzzing.fuzzer_utils.Fuzzer import Fuzzer
from custom_components.test.fuzzing.fuzzer_utils.ValuePool import ValuePool


class ValuePoolFuzzer(Fuzzer):
    """Value pool fuzzer class, inherits from the abstract fuzzer class."""

    value_pool = ValuePool()

    def __int__(self):
        """constructor"""

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
        logger = logging.getLogger(__name__)
        # Valid types for fuzzing
        valid_types = {
            "INT": self.value_pool.get_int(),
            "UINT": self.value_pool.get_uint(),
            "FLOAT": self.value_pool.get_float(),
            "STRING": self.value_pool.get_string(),
            "BOOL": self.value_pool.get_bool(),
            "BYTE": self.value_pool.get_byte(),
            "LIST": self.value_pool.get_list(),
            "DICT": self.value_pool.get_dict(),
            "DATE": self.value_pool.get_date(),
            "ALL": self.value_pool.get_all_values()
        }

        # Validate parameters
        if param_nr <= 0:
            logger.error("Param Nr smaller or equal 0")
            raise ValueError("param_nr must be a positive integer.")
        if len(types) != param_nr:
            logger.error("Length of types list must be equal to param_nr.")
            raise ValueError("Length of types list must be equal to param_nr.")
        if param_combi <= 0 or param_combi > param_nr:
            logger.error("param_combi must be between 1 and param_nr.")
            raise ValueError("param_combi must be between 1 and param_nr.")

        # Generate the individual value pools for each type
        value_pools = []
        for t in types:
            if t not in valid_types:
                logger.error("Invalid type " + str(t) + "specified.")
                raise ValueError(f"Invalid type '{t}' specified.")
            
        dummy_list = [
            [-1, -1, 0, 3, 6],
            [0, 0, 0, 0, 0],
            [-1, -1, 0, 5, 6],
        ]
            


        return dummy_list
