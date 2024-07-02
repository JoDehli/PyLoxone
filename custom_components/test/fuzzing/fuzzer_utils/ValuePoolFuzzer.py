import logging
import itertools
import json

from custom_components.test.fuzzing.fuzzer_utils.Fuzzer import Fuzzer
from custom_components.test.fuzzing.fuzzer_utils.GrammarFuzzer import GrammarFuzzer
from custom_components.test.fuzzing.fuzzer_utils.ValuePool import ValuePool
from custom_components.test.fuzzing.fuzzer_utils.grammar_pool import grammar_controls_json, grammar_ipv4, \
    grammar_loxconfig_rooms_cats_json


class ValuePoolFuzzer(Fuzzer):
    """Value pool fuzzer class, inherits from the abstract fuzzer class."""

    __logger = None

    __value_pool: ValuePool = None
    __grammar_fuzzer: GrammarFuzzer = None

    def __init__(self):
        """constructor"""
        self.__logger = logging.getLogger(__name__)
        self.__value_pool = ValuePool()
        self.__grammar_fuzzer = GrammarFuzzer()

    def __get_fuzzing_pool(
            self, value_pools: list[list], param_combi: int
    ) -> list[list]:
        """
        Generates combinations of the values in the provided lists.

        :param value_pools: A list containing inner lists of values.
        :type lists: list of lists
        :param param_combi: Number of parameters to be combined.
        :type param_combi: int

        :return: A list with combinations of values, ready for fuzzing
        :rtype: list of lists
        """
        value_pool_limited: list[list] = []
        i: int = 0
        while i < param_combi:
            value_pool_limited.append(value_pools[i])
            i += 1

        return_lists: list[list] = [
            list(t) for t in itertools.product(*value_pool_limited)
        ]

        if param_combi > 1:
            # Adjust the shift to evenly distribute each element
            for m in range(param_combi, len(value_pools)):
                pool: list = value_pools[m]
                pool_index: int = 0
                cnt_return_lists: int = 0
                # Distribute the additional pools over the already generated lists
                while cnt_return_lists < len(return_lists):
                    if pool_index >= len(pool):
                        pool_index = 0
                    # Calculate the index-shift for even distribution
                    if cnt_return_lists % len(value_pools[1]) == 0:
                        pool_index = (cnt_return_lists // len(value_pools[1])) * (m - param_combi + 1)
                        if pool_index >= len(pool):
                            pool_index = m - param_combi
                            if pool_index >= len(pool):
                                pool_index = 0
                    return_lists[cnt_return_lists].append(pool[pool_index])
                    pool_index += 1
                    cnt_return_lists += 1
        else:
            # Create return_lists with one element from the first value pool
            return_lists = [[item] for item in value_pools[0]]
            # Add elements from the other value pools
            vp_index: int = 1
            while vp_index < len(value_pools):
                pool = value_pools[vp_index]
                return_lists_index: int = 0
                pool_index: int = 0
                while return_lists_index < len(return_lists):

                    # If the pool_index is greater than the length of the current pool, start from the beginning
                    if pool_index >= len(pool):
                        pool_index = 0
                    return_lists[return_lists_index].append(pool[pool_index])
                    return_lists_index += 1
                    pool_index += 1

                vp_index += 1

        return return_lists

    def fuzz(self, types: list = ["INT"], param_combi: int = 1) -> list:
        """
        Generates an individual value pool for fuzzing based on the parameters.

        :param types: A list of required data types.
        :type types: list, defaults to ["INT"]
        :param param_combi: Maximum number of parameter combinations.
        :type param_combi: int, defaults to 1


        :raises ValueError: If length of types list is not positive.
        :raises ValueError: If param_combi is not between 1 and len(types).

        :return: The value pool for fuzzing.
        :rtype: list of lists
        """

        # Validate input parameters
        if len(types) <= 0:
            self.__logger.error("Length of types list must be positive.")
            raise ValueError("Length of types list must be positive.")
        if param_combi <= 0 or param_combi > len(types):
            self.__logger.error("param_combi must be between 1 and len(types).")
            raise ValueError("param_combi must be between 1 and len(types).")

        # Get the value pools for the valid types
        valid_types = {
            "INT": self.__value_pool.get_int(),
            "UINT": self.__value_pool.get_uint(),
            "FLOAT": self.__value_pool.get_float(),
            "STRING": self.__value_pool.get_string(),
            "BOOL": self.__value_pool.get_bool(),
            "BYTE": self.__value_pool.get_byte(),
            "LIST": self.__value_pool.get_list(),
            "DICT": self.__value_pool.get_dict(),
            "DATE": self.__value_pool.get_date(),
            "ALL": self.__value_pool.get_all_values(),
            "GRAMMAR_IPV4_MIN": [
                self.__grammar_fuzzer.fuzz_min_cost(grammar_ipv4, "<IPv4>")
            ],
            "GRAMMAR_IPV4_MAX": [
                self.__grammar_fuzzer.fuzz_max_cost(grammar_ipv4, "<IPv4>", 2)
            ],
            "GRAMMAR_IPV4_COV": self.__grammar_fuzzer.fuzz_grammar_coverage(
                grammar_ipv4, "<IPv4>"
            ),
            "GRAMMAR_CONTROLS_JSON_MIN": [
                json.loads(self.__grammar_fuzzer.fuzz_min_cost(grammar_controls_json, "<JSON>")), ],
            "GRAMMAR_CONTROLS_JSON_MAX": [
                json.loads(self.__grammar_fuzzer.fuzz_max_cost(grammar_controls_json, "<JSON>", 6)), ],
            "GRAMMAR_CONTROLS_JSON_COV": list(map(lambda x: json.loads(x),
                                                  self.__grammar_fuzzer.fuzz_grammar_coverage(grammar_controls_json,
                                                                                              "<JSON>"))),
            "GRAMMAR_LOXCONFIG_ROOMS_CATS_JSON_MIN": [
                json.loads(self.__grammar_fuzzer.fuzz_min_cost(grammar_loxconfig_rooms_cats_json, "<JSON>"))],
            "GRAMMAR_LOXCONFIG_ROOMS_CATS_JSON_MAX": [
                json.loads(self.__grammar_fuzzer.fuzz_max_cost(grammar_loxconfig_rooms_cats_json, "<JSON>", 6))],
            "GRAMMAR_LOXCONFIG_ROOMS_CATS_JSON_COV": list(map(lambda x: json.loads(x),
                                                         self.__grammar_fuzzer.fuzz_grammar_coverage(
                                                             grammar_loxconfig_rooms_cats_json,
                                                             "<JSON>"))),
        }

        data: list = []

        for type in types:
            # Check whether requested types are valid.
            if type not in valid_types:
                self.__logger.error("Invalid type " + str(type) + " specified.")
                raise ValueError(f"Invalid type '{type}' specified.")
            else:
                # Creating list of the value_pool lists provided in types
                data.append(valid_types[type])

        # Sort the value pools by length in descending order
        sorted_indices = sorted(
            range(len(data)), key=lambda i: len(data[i]), reverse=True
        )
        value_pools: list[list] = [data[i] for i in sorted_indices]
        value_pools = self.__get_fuzzing_pool(value_pools, param_combi)
        # Sort the resulting lists back into the original order
        result: list[list] = []

        value_pool_index: int = 0
        while value_pool_index < len(value_pools):
            reordered_list: list = []
            vp: list = value_pools[value_pool_index]
            m: int = 0
            while m < len(vp):
                reordered_list.append(vp[sorted_indices.index(m)])
                m += 1
            value_pool_index += 1
            result.append(reordered_list)

        return result
