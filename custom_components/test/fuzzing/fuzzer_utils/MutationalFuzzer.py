import logging
import random

from custom_components.test.fuzzing.fuzzer_utils.Fuzzer import Fuzzer


class MutationalFuzzer(Fuzzer):
    """Mutational fuzzer class, inherits from the abstract fuzzer class."""

    _logger = None

    def __init__(self):
        """Constructor get the logger."""
        self._logger = logging.getLogger(__name__)

    def __delete_random_char(self, string: str) -> str:
        """Returns string with a random character deleted.

        This function takes a string `string` as input and returns a new string
        with one random character removed from it.

        :param string: Any string from which a character is to be removed.
        :type string: str

        :return: Returns the input string `string` with one randomly chosen character deleted.
        :rtype: str
        """
        if string == "":
            # If the string is empty, there's no character to delete, so return the empty string.
            return string

        # Generate a random integer position within the range of the string's indices.
        pos = random.randint(0, len(string) - 1)

        # Create a new string by excluding the character at the random position.
        # This is done by concatenating the substring before the random position and
        # the substring after the random position.
        return string[:pos] + string[pos + 1 :]

    def __insert_random_char(self, string: str) -> str:
        """Returns string with a random character inserted.

        This function takes a string `string` as input and returns a new string
        with a random character inserted at a random position within the string.

        :param string: Any string where a character is to be inserted.
        :type string: str

        :return: Returns the input string `string` with one randomly chosen character inserted at a random position.
        :rtype: str
        """
        # Generate a random position within the range of the string's length (including the end of the string).
        pos = random.randint(0, len(string))

        # Generate a random character from the ASCII range 32 to 126 (printable characters).
        random_character = chr(random.randrange(32, 127))

        # Create a new string by inserting the random character at the random position.
        # This is done by concatenating the substring before the random position, the random character,
        # and the substring after the random position.
        return string[:pos] + random_character + string[pos:]

    def __flip_random_char(self, string: str) -> str:
        """Returns string with a random bit flipped in a random position.

        This function takes a string `string` as input and returns a new string
        where one randomly chosen character has one of its bits flipped
        at a random bit position.

        :param string: Any string where a character's bit is to be flipped.
        :type string: str

        :return: Returns the input string `string` with one character's bit flipped at a random position.
        :rtype: str
        """
        if string == "":
            # If the string is empty, there's no character to flip, so return the empty string.
            return string

        # Generate a random integer position within the range of the string's indices.
        pos = random.randint(0, len(string) - 1)

        # Get the character at the randomly chosen position.
        c = string[pos]

        # Generate a random bit position between 0 and 6 (since we are assuming 7-bit ASCII characters).
        bit = 1 << random.randint(0, 6)

        # Flip the bit at the generated bit position using XOR.
        new_c = chr(ord(c) ^ bit)

        # Create a new string by replacing the character at the random position with the new character.
        # This is done by concatenating the substring before the random position, the new character,
        # and the substring after the random position.
        return string[:pos] + new_c + string[pos + 1 :]

    def __int_add_random_(self, number: int) -> int:
        """TODO"""

        bits: int = 32
        random_int: int = random.getrandbits(bits)
        number += random_int

        return number

    def __int_sub_random_(self, number: int) -> int:
        bits: int = 32
        random_int: int = random.getrandbits(bits)
        number -= random_int

        return number

    def __int_mult_random_(self, number: int) -> int:
        random_int: int = random.randint(0, 100)  # bigger?
        number *= random_int

        return number

    def __int_div_random_(self, number: int) -> int:
        bits: int = 32
        random_int: int = random.getrandbits(bits)

        result: int = number // random_int
        return result

    def __float_add_random_(self, n: float) -> float:
        return n

    def __float_sub_random_(self, n: float) -> float:
        return n

    def __float_mult_random_(self, n: float) -> float:
        return n

    def __float_div_random_(self, n: float) -> float:
        return n

    def fuzz(
        self,
        seed: list[int, float, str],
        rounds: int = 1,
    ) -> list[list]:
        """The function returns a param_set for a ParamRunner. The seed is changed randomly in any number of rounds (defined by rounds).

        :param seed: The seed is a list of starting values. The entries must correspond to the valid function parameters of the function to be tested. For example, if the function under test expects an int, float and a string, a possible seed would be [256, 128.5, "demo"]. Only int, float or strings are permitted.
        :type seed: list with any number of int double or strings
        :param rounds: Specifies how many param_set's are to be supplied for the runner. The default is 1.
        :type rounds: int

        :return: Returns a list of lists. Each list in the list is a test case for the ParamRunner.
        :rtype: list
        """

        result_list: list[list] = []

        # Check types of the input seed
        for type in seed:
            if isinstance(type, int):
                self._logger.debug(str(type) + " is instance of int.")
            elif isinstance(type, float):
                self._logger.debug(str(type) + " is instance of float.")
            elif isinstance(type, str):
                self._logger.debug(str(type) + " is instance of str.")
            else:
                self._logger.error(
                    str(type) + " is not a instance of int, float or str."
                )
                raise TypeError(
                    str(type)
                    + " is not a instance of int, float or str."
                    + " The MutationalFuzzer can only fuzz these types!"
                )

        # Add seed as first param set
        result_list.append(seed)
        self._logger.debug("Creat new param_set: " + str(seed) + " in round: 0")

        current_round: int = 1
        next_param_set: list = []
        while current_round < rounds:
            next_param_set = []

            last_param_set = result_list[-1]

            for value in last_param_set:
                if isinstance(value, int):
                    random_case = random.randint(0, 3)
                    match random_case:
                        case 0:
                            self._logger.debug(
                                "Fuzz '" + str(value) + "' with __int_add_random_()"
                            )
                            next_param_set.append(self.__int_add_random_(value))
                        case 1:
                            self._logger.debug(
                                "Fuzz '" + str(value) + "' with __int_sub_random_()"
                            )
                            next_param_set.append(self.__int_sub_random_(value))
                        case 2:
                            self._logger.debug(
                                "Fuzz '" + str(value) + "' with __int_mult_random_()"
                            )
                            next_param_set.append(self.__int_mult_random_(value))
                        case 3:
                            self._logger.debug(
                                "Fuzz '" + str(value) + "' with __int_div_random_()"
                            )
                            next_param_set.append(self.__int_div_random_(value))
                        case default:
                            self._logger.warning(
                                "The fuzz mode "
                                + str(random_case)
                                + " is not specified. Use the __int_add_random_() function"
                            )
                            next_param_set.append(self.__int_add_random_(value))

                elif isinstance(value, float):

                    next_param_set.append(1.1)
                elif isinstance(value, str):
                    random_case = random.randint(0, 2)
                    match random_case:
                        case 0:
                            self._logger.debug(
                                "Fuzz '" + str(value) + "' with __delete_random_char()"
                            )
                            next_param_set.append(self.__delete_random_char(value))
                        case 1:
                            self._logger.debug(
                                "Fuzz '" + str(value) + "' with __insert_random_char()"
                            )
                            next_param_set.append(self.__insert_random_char(value))
                        case 2:
                            self._logger.debug(
                                "Fuzz '" + str(value) + "' with __flip_random_char()"
                            )
                            next_param_set.append(self.__flip_random_char(value))
                        case default:
                            self._logger.warning(
                                "The fuzz mode "
                                + str(random_case)
                                + " is not specified. Use the __flip_random_char() function"
                            )
                            next_param_set.append(self.__flip_random_char(value))

                else:
                    self._logger.error(
                        str(value)
                        + " is not a instance of int, float or str."
                        + " Keep value, value is not longer fuzzed."
                    )
                    next_param_set.append(value)

            self._logger.debug(
                "Creat new param_set: "
                + str(next_param_set)
                + " in round: "
                + str(current_round)
            )
            result_list.append(next_param_set)
            current_round += 1

        self._logger.debug("Generated param_set: " + str(result_list))
        return result_list
