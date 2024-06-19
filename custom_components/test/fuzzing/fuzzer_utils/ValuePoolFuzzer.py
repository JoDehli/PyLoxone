import logging
import itertools

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
    
    def __get_fuzzing_pool(self, value_pools, param_combi):
        """
        Generates combinations of the values in the provided lists.

        :param value_pools: A list containing inner lists of values.
        :type lists: list of lists
        :param param_combi: Number of parameters to be combined.
        :type param_combi: int
        
        :return: A list with combinations of values, ready for fuzzing
        :rtype: list of lists
        """
        value_pool_limited = []
        i = 0
        while i < param_combi:
            value_pool_limited.append(value_pools[i])
            i += 1

        return_lists = [list(t) for t in itertools.product(*value_pool_limited)]



        if param_combi > 1:
            # Anpassung der Verschiebung, um jedes Element gleichmäßig zu verteilen
            for m in range(param_combi, len(value_pools)):
                pool = value_pools[m]
                l = 0
                n = 0
                # Verteilt die zusätzlichen Pools auf die bereits erzeugten Listen
                while n < len(return_lists):
                    if l >= len(pool):
                        l = 0
                     # Berechnung des Index-Shifts für die gleichmäßige Verteilung
                    if n % len(value_pools[1]) == 0:
                        l = (n // len(value_pools[1])) * (m - param_combi + 1)
                        if l >= len(pool):
                            l = m - param_combi
                
                    return_lists[n].append(pool[l])
                    l += 1    
                    n += 1
        else:
            # Erzeuge return_lists mit jeweils einem Element aus dem ersten Werte-Pool
            return_lists = [[item] for item in value_pools[0]]
            # Füge Elemente aus den weiteren Werte-Pools hinzu
            i = 1
            while i < len(value_pools):
                pool = value_pools[i]
                j = 0
                k = 0
                while j < len(return_lists):
                    
                    # Falls der Index k größer ist als die Länge des aktuellen Pools, beginne von vorne
                    if k >= len(pool):
                        k = 0
                    return_lists[j].append(pool[k])
                    j += 1
                    k += 1
                    
                i += 1
                            
        return return_lists

    def fuzz(
       self, types: list = ["INT"], param_combi: int = 1
    ) -> list:
        """
        Generates an individual value pool for fuzzing based on the parameters.

        :param types: A list of required data types. The list must be the same length as param_nr.
        :type types: list, defaults to ["INT"]
        :param param_combi: Maximum number of parameter combinations.
        :type param_combi: int, defaults to 1


        :raises ValueError: If length of types list is not positive.
        :raises ValueError: If param_combi is not between 1 and len(types).

        :return: The value pool for fuzzing.
        :rtype: list of lists
        """

        #self.logger.warning("The var param_combi is not in use!")

        # Validate input parameters
        if len(types) <= 0:
            self.logger.error("Length of types list must be positive.")
            raise ValueError("Length of types list must be positive.")
        if param_combi <= 0 or param_combi > len(types):
            self.logger.error("param_combi must be between 1 and len(types).")
            raise ValueError("param_combi must be between 1 and len(types).")

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
            "GRAMMAR_IPV4_MIN": [self.__grammar_fuzzer.fuzz_min_cost(grammar_ipv4, "<IPv4>")],
            "GRAMMAR_IPV4_MAX": [self.__grammar_fuzzer.fuzz_max_cost(grammar_ipv4, "<IPv4>", 2)],
            "GRAMMAR_IPV4_COV": self.__grammar_fuzzer.fuzz_grammar_coverage(grammar_ipv4, "<IPv4>"),
        }

        data = []

        for t in types:
            # Check whether requested types are valid.
            if t not in valid_types:
                self.logger.error("Invalid type " + str(t) + "specified.")
                raise ValueError(f"Invalid type '{t}' specified.")
            else:
                # Creating list of the value_pool lists provided in types
                data.append(valid_types[t])
        
        # Sortiere die Werte-Pools nach Länge in absteigender Reihenfolge
        sorted_indices = sorted(range(len(data)), key=lambda i: len(data[i]), reverse=True)
        value_pools = [data[i] for i in sorted_indices]
        value_pools = self.__get_fuzzing_pool(value_pools, param_combi)
        # Sortiere die resultierenden Listen wieder in die ursprüngliche Reihenfolge
        result = []
        
        l = 0
        while l < len(value_pools):
            reordered_list = []
            vp = value_pools[l]
            m = 0
            while m < len(vp):
                reordered_list.append(vp[sorted_indices.index(m)])
                m += 1
            l += 1
            result.append(reordered_list)
                 
        return result


        
