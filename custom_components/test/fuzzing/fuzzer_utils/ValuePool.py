import sys
from itertools import product


class ValuePool:
    """Provides value pool for value-pool based fuzzing approches."""

    _UINT_POOL = []
    _INT_POOL = []
    _FLOAT_POOL = []

    def __init__(self) -> None:
        """Constructor
        Set values for pools.

        sys.maxsize: An integer giving the maximum value a variable of type Py_ssize_t can take. It's usually 2^31 - 1 on a 32-bit platform and 2^63 - 1 on a 64-bit platform.
        """
        self.INT_POOL = [
            sys.maxsize * -sys.maxsize,
            -sys.maxsize,
            -257,
            -1,
            0,
            1,
            257,
            sys.maxsize,
            sys.maxsize * sys.maxsize,
        ]

        self.UINT_POOL = [
            0,
            1,
            257,
            sys.maxsize,
            sys.maxsize * sys.maxsize,
        ]

        self.FLOAT_POOL = [
            sys.maxsize * -sys.maxsize * 0.5,
            -sys.maxsize * 0.5,
            -257.0,
            -1.0,
            0.0,
            1.0,
            257.0,
            sys.maxsize * 0.5,
            sys.maxsize * sys.maxsize * 0.5,
        ]

    def get_unit(self) -> list:
        return self._UINT_POOL

#     def get_all_combinations_of_pool(self, pool: list, parmeters: int) -> list:
#         """Generate all possible combinations of elements in a pool, with repetition.

#         :param pool: A list of elements from which combinations will be formed.
#         :type pool: list
#         :param parameters: The number of elements in each combination.
#         :type parameters: int
#         :return: A list containing all possible combinations of elements from the pool.
#         :rtype: list
#         """
#         all_combinations = list(product(pool, repeat=parmeters))
#         return all_combinations

#     def dummy(funktion):
#         funktion("xx")


# ValuePool.dummy(print)
