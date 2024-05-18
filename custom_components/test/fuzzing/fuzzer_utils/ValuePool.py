import sys


class ValuePool:
    """Provides value pool for value-pool based fuzzing approches."""

    _UINT_POOL = []
    _INT_POOL = []
    _FLOAT_POOL = []

    def __init__(self) -> None:
        """constructor
        Set values for pools.

        TODO: @jonathanheitzmann add more value pool
        TODO: @jonathanheitzmann add one pool with all values
        TODO: @jonathanheitzmann no dublicate pool values, like in Balista. e.g. _FLOAT_POOL copyyinherits values from _INT_POOL

        sys.maxsize: An integer giving the maximum value a variable of type Py_ssize_t can take. It's usually 2^31 - 1 on a 32-bit platform and 2^63 - 1 on a 64-bit platform.
        """
        # set values for _INT_POOL
        self._INT_POOL = [
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

        # set values for _UINT_POOL
        self._UINT_POOL = [
            0,
            1,
            257,
            sys.maxsize,
            sys.maxsize * sys.maxsize,
        ]

        # set values for _FLOAT_POOL
        self._FLOAT_POOL = [
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

    def get_uint(self) -> list:
        return self._UINT_POOL

    def get_int(self) -> list:
        return self._INT_POOL

    def get_float(self) -> list:
        return self._FLOAT_POOL
