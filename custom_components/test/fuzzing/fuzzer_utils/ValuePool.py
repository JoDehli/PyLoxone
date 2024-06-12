import sys
import datetime


class ValuePool:
    """Provides value pool for value-pool based fuzzing approches."""

    _UINT_POOL = []
    _INT_POOL = []
    _FLOAT_POOL = []
    _STRING_POOL = []
    _BOOL_POOL = []
    _BYTE_POOL = []
    _LIST_POOL = []
    _DICT_POOL = []
    _DATE_POOL = []
    _ALL_VALUES_POOL = []

    def __init__(self) -> None:
        """constructor
        Set values for pools.

        sys.maxsize: An integer giving the maximum value a variable of type Py_ssize_t can take. It's usually 2^31 - 1 on a 32-bit platform and 2^63 - 1 on a 64-bit platform.
        """
        # set values for _UINT_POOL
        self._UINT_POOL = [
            0,
            1,
            257,
            sys.maxsize,
            sys.maxsize * sys.maxsize,
        ]

        # set values for _INT_POOL
        self._INT_POOL = [
            sys.maxsize * -sys.maxsize,
            -sys.maxsize,
            -257,
            -1,
        ] + self._UINT_POOL

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
        ] + self._INT_POOL

        # set values for _STRING_POOL
        self._STRING_POOL = [
            None,
            "",
            "a",
            "abc",
            " " * 100,  # long string of spaces
            "special_characters_!@#$%^&*()",
            "üñîçødê",
            "a" * 1000,  # very long string
        ]

        # set values for _BOOL_POOL
        self._BOOL_POOL = [
            None,
            True,
            False,
        ]

        # set values for _BYTE_POOL
        self._BYTE_POOL = [
            b"",
            b"\x00",
            b"abc",
            bytes(range(256)),  # all possible byte values
        ]

        # set values for _LIST_POOL
        self._LIST_POOL = [
            None,
            [],
            [1, 2, 3],
            ["a", "b", "c"],
            [True, False, None],
            list(range(100)),  # long list
        ]

        # set values for _DICT_POOL
        self._DICT_POOL = [
            None,
            {},
            {"key": "value"},
            {"int": 1, "float": 1.0, "str": "string"},
            {i: i for i in range(10)},  # dictionary with multiple entries
        ]

        # set values for _DATE_POOL
        self._DATE_POOL = [
            None,
            datetime.datetime.min,
            datetime.datetime.max,
            datetime.datetime.now(),
            datetime.datetime(2000, 1, 1),
            datetime.datetime(1970, 1, 1),
        ]

        # create a pool with all unique values
        self._ALL_VALUES_POOL = (
            self._INT_POOL
            + self._UINT_POOL
            + self._FLOAT_POOL
            + self._STRING_POOL
            + self._BOOL_POOL
            + self._BYTE_POOL
            + self._LIST_POOL
            + self._DICT_POOL
            + self._DATE_POOL
        )

    def get_uint(self) -> list:
        return self._UINT_POOL

    def get_int(self) -> list:
        return self._INT_POOL

    def get_float(self) -> list:
        return self._FLOAT_POOL

    def get_string(self) -> list:
        return self._STRING_POOL

    def get_bool(self) -> list:
        return self._BOOL_POOL

    def get_byte(self) -> list:
        return self._BYTE_POOL

    def get_list(self) -> list:
        return self._LIST_POOL

    def get_dict(self) -> list:
        return self._DICT_POOL

    def get_date(self) -> list:
        return self._DATE_POOL

    def get_all_values(self) -> list:
        return self._ALL_VALUES_POOL
