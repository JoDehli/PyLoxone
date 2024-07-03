import sys
import datetime


class ValuePool:
    """Provides value pool for value-pool based fuzzing approches."""

    __UINT_POOL = []
    __INT_POOL = []
    __FLOAT_POOL = []
    __STRING_POOL = []
    __BOOL_POOL = []
    __BYTE_POOL = []
    __LIST_POOL = []
    __DICT_POOL = []
    __DATE_POOL = []
    __ALL_VALUES_POOL = []

    def __init__(self) -> None:
        """constructor
        Set values for pools.

        sys.maxsize: An integer giving the maximum value a variable of type Py_ssize_t can take. It's usually 2^31 - 1 on a 32-bit platform and 2^63 - 1 on a 64-bit platform.
        """
        # set values for __UINT_POOL
        self.__UINT_POOL = [
            0,
            1,
            257,
            sys.maxsize,
            sys.maxsize * sys.maxsize,
        ]

        # set values for __INT_POOL
        self.__INT_POOL = [
            sys.maxsize * -sys.maxsize,
            -sys.maxsize,
            -257,
            -1,
        ] + self.__UINT_POOL

        # set values for __FLOAT_POOL
        self.__FLOAT_POOL = [
            sys.maxsize * -sys.maxsize * 0.5,
            -sys.maxsize * 0.5,
            -257.0,
            -1.0,
            0.0,
            1.0,
            257.0,
            sys.maxsize * 0.5,
            sys.maxsize * sys.maxsize * 0.5,
        ] + [x * 1.1 for x in self.__INT_POOL]

        # set values for __STRING_POOL
        self.__STRING_POOL = [
            "",
            "a",
            "abc",
            " " * 100,  # long string of spaces
            "special_characters_!@#$%^&*()",
            "üñîçødê",
            "a" * 1000,  # very long string
        ]

        # set values for __BOOL_POOL
        self.__BOOL_POOL = [
            None,
            True,
            False,
            0,
            1,
        ]

        # set values for __BYTE_POOL
        self.__BYTE_POOL = [
            b"",
            b"\x00",
            b"abc",
            bytes(range(256)),  # all possible byte values
        ]

        # set values for __LIST_POOL
        self.__LIST_POOL = [
            None,
            [],
            [1, 2, 3],
            ["a", "b", "c"],
            [True, False, None],
            list(range(100)),  # long list
        ]

        # set values for __DICT_POOL
        # a dict is represented as a string and need to be loaded as a json in the testcase
        self.__DICT_POOL = [
            # None, # test cases can today not handel a None value, the JSON bib can load a NONE value as a JSON
            "{}",
            '{"key": "value"}',
            '{"int": 1, "float": 1.0, "str": "string"}',
            '{"0": 0, "1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8, "9": 9}',
        ]

        # set values for __DATE_POOL
        self.__DATE_POOL = [
            None,
            datetime.datetime.min,
            datetime.datetime.max,
            datetime.datetime.now(),
            datetime.datetime(2000, 1, 1),
            datetime.datetime(1970, 1, 1),
        ]

        # create a pool with all unique values
        self.__ALL_VALUES_POOL = (
            self.__INT_POOL
            + self.__UINT_POOL
            + self.__FLOAT_POOL
            + self.__STRING_POOL
            + self.__BOOL_POOL
            + self.__BYTE_POOL
            + self.__LIST_POOL
            + self.__DICT_POOL
            + self.__DATE_POOL
        )

    def get_uint(self) -> list:
        return self.__UINT_POOL

    def get_int(self) -> list:
        return self.__INT_POOL

    def get_float(self) -> list:
        return self.__FLOAT_POOL

    def get_string(self) -> list:
        return self.__STRING_POOL

    def get_bool(self) -> list:
        return self.__BOOL_POOL

    def get_byte(self) -> list:
        return self.__BYTE_POOL

    def get_list(self) -> list:
        return self.__LIST_POOL

    def get_dict(self) -> list:
        return self.__DICT_POOL

    def get_date(self) -> list:
        return self.__DATE_POOL

    def get_all_values(self) -> list:
        return self.__ALL_VALUES_POOL
