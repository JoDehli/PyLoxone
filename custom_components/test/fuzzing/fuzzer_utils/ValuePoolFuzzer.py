from itertools import product
import logging


from custom_components.test.fuzzing.fuzzer_utils.Fuzzer import Fuzzer
from custom_components.test.fuzzing.fuzzer_utils.ValuePool import ValuePool

def generate_ranking(lists):
    # generates ranking based on length of the lists
    rank = sorted(range(len(lists)), key=lambda x: (-len(lists[x]), x))
    return rank

def get_repeater(lists, param_combi, m):
    #if param_combi is greater than 1 lists have to be repeated, here it is calculated how often a list must be repeated
    repeater = 1
    param_combi_count = 1
    while param_combi_count < param_combi:
        if m >= param_combi_count:
            repeater = repeater * len(lists[m-1])
        param_combi_count += 1
        
    return repeater-1
    
def generate_new_list(lists, param_combi, rank):
    new_lists = []
    spare_list = []
    new_spare_list = []
        

    m = 0
    while m < len(lists):
        repeater = get_repeater(lists, param_combi, m)
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
                    spare_list.append(spare_list[0]) #if the length of a list is smaller than the longest list we have to fill it, it could probably be more elegant
                    q += 1
                while r < repetition_counter:
                    new_spare_list.append(spare_list[o])
                    index += 1
                    r += 1
                o += 1
            p = len(lists[rank[m]])
                
            repeater_count += 1
                

        new_lists.append(new_spare_list)
        #print(new_lists)
                
        m += 1
        
    return new_lists
    
def generate_combinations(lists, param_combi):
    #print("Input lists:", lists)
        
    rank = generate_ranking(lists) #ranking over length of lists

    new_list = generate_new_list(lists, param_combi, rank)

    return new_list

class ValuePoolFuzzer(Fuzzer):
    """Value pool fuzzer class, inherits from the abstract fuzzer class."""

    value_pool = ValuePool()

    def __int__(self):
        """constructor"""

    def fuzz(
        self, param_nr: int = 1, types: list = ["INT"], param_combi: int = 1
    ) -> list:
        """Generates an individual value pool for fuzzing based on the parameters. A list of lists is returned.

        TODO: @jonathanheitzmann implement function of param_combi

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
        logger.warning("The var param_combi is not in use!")

        # Validate input parameters
        if param_nr <= 0:
            logger.error("Param Nr smaller or equal 0")
            raise ValueError("param_nr must be a positive integer.")
        if len(types) != param_nr:
            logger.error("Length of types list must be equal to param_nr.")
            raise ValueError("Length of types list must be equal to param_nr.")
        if param_combi <= 0 or param_combi > param_nr:
            logger.error("param_combi must be between 1 and param_nr.")
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
        }

        # Check whether requested types are valid.
        for t in types:
            if t not in valid_types:
                logger.error("Invalid type " + str(t) + "specified.")
                raise ValueError(f"Invalid type '{t}' specified.")

        value_pools = []
        for t in types:
            value_pools.append(valid_types[t])#creating list of the value_pool lists needed

        result = generate_combinations(value_pools, param_combi)

            
        return result
