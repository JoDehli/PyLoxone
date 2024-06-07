import logging
import random
import math

from custom_components.test.fuzzing.fuzzer_utils.Fuzzer import Fuzzer


class MutationalFuzzer(Fuzzer):
    """Mutational fuzzer class, inherits from the abstract fuzzer class."""

    _logger = None
    _multiplier: list[int] = []

    def __init__(self):
        """Constructor get the logger."""
        self._logger = logging.getLogger(__name__)

        i: int = 10
        while i <= 10000000000000000:
            self._multiplier.append(i)
            i *= 10

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

    def __get_random_float(self) -> float:
        """TODO"""
        random_float = random.random()
        random_float *= random.choice(self._multiplier)

        return random_float

    def __check_inf(self, number: float) -> float:
        """TODO"""
        if math.isinf(number):
            number = random.random()
            self._logger.info(
                "The return value would be - or + INF, set it to an random value between 0.0 and 1.0"
            )

        return number

    def __add_random_number(self, number: float) -> float:
        """TODO"""
        number += self.__get_random_float()

        return self.__check_inf(number)

    def __sub_random_number(self, number: float) -> float:
        """TODO"""
        number -= self.__get_random_float()

        return self.__check_inf(number)

    def __mult_random_number(self, number: float) -> float:
        """TODO"""
        number *= self.__get_random_float()

        return self.__check_inf(number)

    def __div_random_number(self, number: float) -> float:
        """TODO"""
        number /= self.__get_random_float()

        return self.__check_inf(number)

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
        ### Check types of the input seed ###############################################
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
        #################################################################################

        result_list: list[list] = []
        # Add seed as first param set
        result_list.append(seed)
        self._logger.debug("Creat new param_set: " + str(seed) + " in round: 0")

        current_round: int = 1
        next_param_set: list = []
        while current_round < rounds:
            next_param_set = []

            last_param_set = result_list[-1]

            for value in last_param_set:
                # Check if the last value was a string.                
                if isinstance(value, str):
                    # Choose randomly one fuzz function.
                    random_case = random.randint(0, 2)
                    match random_case:
                        case 0:
                            next_param_set.append(self.__delete_random_char(value))
                        case 1:
                            next_param_set.append(self.__insert_random_char(value))
                        case 2:
                            next_param_set.append(self.__flip_random_char(value))
                        case default:
                            self._logger.warning(
                                "The fuzz mode "
                                + str(random_case)
                                + " is not specified. Use the __flip_random_char() function"
                            )
                            next_param_set.append(self.__flip_random_char(value))

                # Check if the last value was a int or float. 
                elif isinstance(value, int) or isinstance(value, float):
                    # Choose randomly one fuzz function.
                    random_case = random.randint(0, 3)
                    match random_case:
                        case 0:
                            # If an int is required, cast the float. 
                            if isinstance(value, int):
                                next_param_set.append(
                                    int(self.__add_random_number(value))
                                )

                            else:
                                next_param_set.append(self.__add_random_number(value))
                        case 1:
                            # If an int is required, cast the float. 
                            if isinstance(value, int):
                                next_param_set.append(
                                    int(self.__sub_random_number(value))
                                )

                            else:
                                next_param_set.append(self.__sub_random_number(value))
                        case 2:
                            # If an int is required, cast the float. 
                            if isinstance(value, int):
                                next_param_set.append(
                                    int(self.__mult_random_number(value))
                                )

                            else:
                                next_param_set.append(self.__mult_random_number(value))
                        case 3:
                            # If an int is required, cast the float. 
                            if isinstance(value, int):
                                next_param_set.append(
                                    int(self.__div_random_number(value))
                                )

                            else:
                                next_param_set.append(self.__div_random_number(value))
                        case default:
                            self._logger.warning(
                                "The fuzz mode "
                                + str(random_case)
                                + " is not specified. Use the __int_add_random_() function"
                            )
                            # If an int is required, cast the float. 
                            if isinstance(value, int):
                                next_param_set.append(
                                    int(self.__add_random_number(value))
                                )

                            else:
                                next_param_set.append(self.__add_random_number(value))

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

        self._logger.info("Generated param_set: " + str(result_list))
        return result_list
