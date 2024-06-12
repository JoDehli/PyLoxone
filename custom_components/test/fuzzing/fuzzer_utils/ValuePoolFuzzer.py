import logging
import itertools

from custom_components.test.fuzzing.fuzzer_utils.Fuzzer import Fuzzer
from custom_components.test.fuzzing.fuzzer_utils.ValuePool import ValuePool

#from Fuzzer import Fuzzer
#from ValuePool import ValuePool

class ValuePoolFuzzer(Fuzzer):
    """Value pool fuzzer class, inherits from the abstract fuzzer class."""

    value_pool = ValuePool()

    def __int__(self):
        """constructor"""
    
    '''def __generate_ranking(self, lists):
        """
        Generates ranking based on length of the lists.

        :param lists: A list containing inner lists.
        :type lists: list of lists
        
        :return: A ranking of the lists based on their length.
        :rtype: list
        """
        rank = sorted(range(len(lists)), key=lambda x: (-len(lists[x]), x))
        return rank

    def __get_repeater(self, lists, param_combi, m, rank):
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
        index_rank = rank.index(m)
        print(f"Der param_combi ist {param_combi}")
        repeater = 1
        param_combi_count = 0
        while param_combi_count < param_combi and param_combi_count < index_rank:
            repeater = repeater * len(lists[rank[param_combi_count]])
            param_combi_count += 1
            
        return repeater
    
    def __get_repetition(self, lists, param_combi, m, rank):
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
        index_rank = rank.index(m)
        print(f"Der index ist {index_rank}")
        repetition = 1
        while index_rank + 1 < len(rank) and index_rank < param_combi:
            index_rank += 1
            repetition = repetition * len(lists[rank[index_rank]])
            print(f"len {len(lists[rank[index_rank]])}")
            
            
        return repetition
        
    def __generate_new_list(self, lists, param_combi, rank):
        """
        Generates a new list with recombinations of inner lists.

        :param lists: A list containing inner lists of values.
        :type lists: list of lists
        :param param_combi: Number of parameters to be combined.
        :type param_combi: int
        :param rank: Indices of the lists sorted by their length.
        :type rank: list
        
        :return: A new list with recombinations of the original lists.
        :rtype: list of lists
        """
        new_lists = []
        spare_list = []
        
        print(lists[rank[1]])    

        m = 0
        while m < len(lists):
            repeater = self.__get_repeater(lists, param_combi, m, rank)
            print("Der Reapeater Wert ist:")
            print(repeater)
            repeater_count = 0
            spare_list = []
            new_spare_list = []
            n = m + 1
            repetition_counter = self.__get_repetition(lists, param_combi, m, rank)
            """repetition_counter = 1
            while n < param_combi:
                repetition_counter = repetition_counter * len(lists[rank[n]])
                n += 1"""
            print("Der Reapeatition-counter Wert ist:")
            print(repetition_counter)
            while repeater_count < repeater: 
                
                
                
                  
                    
                o = 0
                index = 0
                while o < len(lists[m]):
                    r = 0
                    spare_list = lists[m]
                    q = len(spare_list)
                    while q < len(lists[rank[0]]):
                        print("Values werden aufgefüllt")
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
            print(f"Length of new_spare_list for m={m}:", len(new_spare_list))        
            m += 1

        return_list = []

        x = 0

        while x < len(new_spare_list):
            y = 0
            new_list_y = []
            return_list_x = []
            while y < len(lists):
                new_list_y = new_lists[y]
                return_list_x.append(new_list_y[x])
                y += 1
            return_list.append(return_list_x)
            x += 1
                
        
        

            
        return return_list
        
    def __generate_combinations(self, lists, param_combi):
        """
        Generates combinations of the values in the provided lists.

        :param lists: A list containing inner lists of values.
        :type lists: list of lists
        :param param_combi: Number of parameters to be combined.
        :type param_combi: int
        
        :return: A list with combinations of values.
        :rtype: list of lists
        """
        rank = self.__generate_ranking(lists)

        new_list = self.__generate_new_list(lists, param_combi, rank)

        return new_list'''
    
    def __n_way_combinations(self, num_lists_combination, *data):
        # Create the Cartesian product of all arrays
        product = list(itertools.product(*data))
        
        # Generate all 2-way combinations from the product
        """combinations = []
        for comb in product:
            # Generate 2-way combinations for each tuple in the product
            combinations.extend(itertools.combinations(comb, len(data)))"""
        
        return product

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

        logger = logging.getLogger(__name__)
        

        # Validate input parameters
        if len(types) <= 0:
            logger.error("Length of types list must be positive.")
            raise ValueError("Length of types list must be positive.")
        if param_combi <= 0 or param_combi > len(types):
            logger.error("param_combi must be between 1 and len(types).")
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
        }

        value_pools = []

        for t in types:
            # Check whether requested types are valid.
            if t not in valid_types:
                logger.error("Invalid type " + str(t) + "specified.")
                raise ValueError(f"Invalid type '{t}' specified.")
            else:
                # Creating list of the value_pool lists provided in types
                value_pools.append(valid_types[t])

        


        #result = self.__generate_combinations(value_pools, param_combi)

        result = self.__n_way_combinations(2, *value_pools)
            
        return result
