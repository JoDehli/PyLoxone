import logging

from custom_components.test.fuzzing.fuzzer_utils.Fuzzer import Fuzzer
from custom_components.test.fuzzing.fuzzer_utils.GrammarFuzzer import GrammarFuzzer
from custom_components.test.fuzzing.fuzzer_utils.ValuePool import ValuePool

from custom_components.test.fuzzing.fuzzer_utils.grammars.grammar_ipv4 import grammar_ipv4


class ValuePoolFuzzer(Fuzzer):
    """Value pool fuzzer class, inherits from the abstract fuzzer class."""

    value_pool = ValuePool()
    logger = logging.getLogger(__name__)

    __grammar_fuzzer = GrammarFuzzer()

    def __init__(self):
        """constructor"""

    def __generate_ranking(self, lists):
        """
        Generates ranking based on length of the lists.

        :param lists: A list containing inner lists.
        :type lists: list of lists

        :return: A ranking of the lists based on their length.
        :rtype: list
        """
        rank = sorted(range(len(lists)), key=lambda x: (-len(lists[x]), x))
        return rank

    def __get_repeater(self, lists, param_combi, m):
        """
        Calculates how often a list must be repeated if param_combi is greater than 1.

        :param lists: A list containing inner lists.
        :type lists: list of lists
        :param param_combi: Number of parameters to be combined.
        :type param_combi: int
        :param m: The current index in the lists.
        :type m: int

        :return: The number of times a list must be repeated.
        :rtype: int
        """
        repeater = 1
        param_combi_count = 1
        while param_combi_count < param_combi:
            if m >= param_combi_count:
                repeater = repeater * len(lists[m - 1])
            param_combi_count += 1

        return repeater - 1

    def __generate_new_list(self, lists, param_combi, rank, param_nr):
        """
        Generates a new list with recombinations of inner lists.

        :param lists: A list containing inner lists of values.
        :type lists: list of lists
        :param param_combi: Number of parameters to be combined.
        :type param_combi: int
        :param rank: Indices of the lists sorted by their length.
        :type rank: list
        :param param_nr: Number of parameters of the function to be fuzzed.
        :type param_combi: int

        :return: A new list with recombinations of the original lists.
        :rtype: list of lists
        """
        new_lists = []
        spare_list = []

        m = 0
        while m < len(lists):
            repeater = self.__get_repeater(lists, param_combi, m)
            repeater_count = 0
            spare_list = []
            new_spare_list = []
            while repeater_count <= repeater:
                n = m + 1
                repetition_counter = 1
                while n < param_combi:
                    repetition_counter = repetition_counter * len(lists[rank[n]])
                    n += 1

                o = 0
                index = 0
                while o < len(lists[rank[m]]):
                    r = 0
                    spare_list = lists[rank[m]]
                    q = len(spare_list)
                    while q < len(lists[rank[0]]):
                        """if the length of a list is smaller than the longest list we have to fill it, it could probably be more elegant"""
                        spare_list.append(spare_list[0])
                        q += 1
                    while r < repetition_counter:
                        new_spare_list.append(spare_list[o])
                        index += 1
                        r += 1
                    o += 1
                p = len(lists[rank[m]])

                repeater_count += 1

            new_lists.append(new_spare_list)

            m += 1

        return_list = []

        x = 0

        while x < len(new_spare_list):
            y = 0
            new_list_y = []
            return_list_x = []
            while y < param_nr:
                new_list_y = new_lists[y]
                return_list_x.append(new_list_y[x])
                y += 1
            return_list.append(return_list_x)
            x += 1

        return return_list

    def __generate_combinations(self, lists, param_combi, param_nr):
        """
        Generates combinations of the values in the provided lists.

        :param lists: A list containing inner lists of values.
        :type lists: list of lists
        :param param_combi: Number of parameters to be combined.
        :type param_combi: int
        :param param_nr: Number of parameters of the function to be fuzzed.
        :type param_combi: int

        :return: A list with combinations of values.
        :rtype: list of lists
        """
        rank = self.__generate_ranking(lists)

        new_list = self.__generate_new_list(lists, param_combi, rank, param_nr)

        return new_list

    def fuzz(
        self, param_nr: int = 1, types: list = ["INT"], param_combi: int = 1
    ) -> list:
        """
        Generates an individual value pool for fuzzing based on the parameters.

        :param param_nr: Number of parameters of the function to be fuzzed. Each list in the return list contains a corresponding number of entries.
        :type param_nr: int, defaults to 1
        :param types: A list of required data types. The list must be the same length as param_nr.
        :type types: list, defaults to ["INT"]
        :param param_combi: Maximum number of parameter combinations.
        :type param_combi: int, defaults to 1

        :raises ValueError: If param_nr is not a positive integer.
        :raises ValueError: If length of types list is not equal to param_nr.
        :raises ValueError: If param_combi is not between 1 and param_nr.

        :return: The value pool for fuzzing.
        :rtype: list of lists
        """

        self.logger.warning("The var param_combi is not in use!")

        # Validate input parameters
        if param_nr <= 0:
            self.logger.error("Param Nr smaller or equal 0")
            raise ValueError("param_nr must be a positive integer.")
        if len(types) != param_nr:
            self.logger.error("Length of types list must be equal to param_nr.")
            raise ValueError("Length of types list must be equal to param_nr.")
        if param_combi <= 0 or param_combi > param_nr:
            self.logger.error("param_combi must be between 1 and param_nr.")
            raise ValueError("param_combi must be between 1 and param_nr.")

        # Get the value pools for the valid types
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
            "ALL": self.value_pool.get_all_values(),
            "GRAMMAR_IPV4_MIN": self.__grammar_fuzzer.fuzz_min_cost(grammar_ipv4, "<IPv4>"),
            "GRAMMAR_IPV4_MAX": self.__grammar_fuzzer.fuzz_max_cost(grammar_ipv4, "<IPv4>", 2),
            "GRAMMAR_IPV4_COV": self.__grammar_fuzzer.fuzz_grammar_coverage(grammar_ipv4, "<IPv4>"),
        }

        value_pools = []

        for t in types:
            # Check whether requested types are valid.
            if t not in valid_types:
                self.logger.error("Invalid type " + str(t) + "specified.")
                raise ValueError(f"Invalid type '{t}' specified.")
            else:
                # Creating list of the value_pool lists provided in types
                value_pools.append(valid_types[t])

        result = self.__generate_combinations(value_pools, param_combi, param_nr)

        return result
