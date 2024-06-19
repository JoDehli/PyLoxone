import logging
import random
import math

from custom_components.test.fuzzing.fuzzer_utils.Fuzzer import Fuzzer


class MutationalBlackBoxFuzzer(Fuzzer):
    """Mutational fuzzer class, inherits from the abstract fuzzer class."""

    __logger = None
    __multiplier: list[int] = []

    def __init__(self):
        """Constructor get the logger."""
        self.__logger = logging.getLogger(__name__)

        i: int = 10
        while i <= 10000000000000000:
            self.__multiplier.append(i)
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
        """Returns a random float value modified by a randomly chosen multiplier.

        This function generates a random float value between 0.0 and 1.0, and then
        multiplies it by a randomly selected value from the list `self.__multiplier`.

        :return: A random positiv float value.
        :rtype: float
        """
        # Generate a random float between 0.0 and 1.0.
        random_float = random.random()

        # Multiply the random float by a randomly chosen multiplier from the list `self.__multiplier`.
        random_float *= random.choice(self.__multiplier)

        # Return the modified random float.
        return random_float

    def __check_inf(self, number: float) -> float:
        """Checks if the number is infinite and replaces it with a random value if true.

        This function takes a floating-point number `number` as input. If the number is
        positive or negative infinity, it replaces the number with a random value between
        0.0 and 1.0. It also logs this replacement.

        :param number: The number to check for infinity.
        :type number: float

        :return: Returns the original number if it is not finite; otherwise, returns a random value between 0.0 and 1.0.
        :rtype: float
        """
        if math.isinf(number):
            # If the number is infinite, replace it with a random value between 0.0 and 1.0.
            number = random.random()
            self.__logger.debug(
                "The return value would be - or + INF, set it to a random value between 0.0 and 1.0"
            )

        # Return the potentially modified number.
        return number

    def __add_random_number(self, number: float) -> float:
        """Returns the input number with a random float added.

        This function takes a floating-point number `number` as input and adds
        a random float to it. The random float is obtained from the private method
        `__get_random_float`.

        :param number: The number to which a random float will be added.
        :type number: float

        :return: Returns the input number `number` with an added random float,
                 after ensuring the result is not infinite using the `__check_inf` method.
        :rtype: float
        """
        number += self.__get_random_float()

        # Check if the resulting number is infinite.
        return self.__check_inf(number)

    def __sub_random_number(self, number: float) -> float:
        """Subtracts a random float from the given number.

        This function takes a float `number` as input and subtracts a randomly
        generated float from it. The resulting number is then checked for
        infinity values using the `__check_inf` method.

        :param number: The input number from which a random float will be subtracted.
        :type number: float

        :return: Returns the resulting number after subtracting a random float and checking for infinity.
        :rtype: float
        """
        number -= self.__get_random_float()

        # Check if the resulting number is infinite.
        return self.__check_inf(number)

    def __mult_random_number(self, number: float) -> float:
        """Returns the result of multiplying the input number by a random float.

        This function takes a floating-point number `number` as input and returns
        a new floating-point number which is the result of multiplying the input
        number by a randomly generated float. It also checks if the result is
        infinite.

        :param number: A floating-point number to be multiplied by a random float.
        :type number: float

        :return: Returns the input number multiplied by a random float,
                 after checking if the result is infinite.
        :rtype: float
        """
        number *= self.__get_random_float()

        # Check if the resulting number is infinite.
        return self.__check_inf(number)

    def __div_random_number(self, number: float) -> float:
        """Divides the input number by a randomly generated float.

        This function takes a float `number` as input and divides it by
        a random float generated by the `__get_random_float` method. It then
        returns the result of this division after checking for infinity.

        :param number: The float number to be divided.
        :type number: float

        :return: Returns the input number divided by a random float.
        :rtype: float
        """
        number /= self.__get_random_float()

        # Check if the resulting number is infinite.
        return self.__check_inf(number)

    def fuzz(
        self,
        seed: list,
        rounds: int = 1,
    ) -> list[list]:
        """The function returns a param_set for a ParamRunner.
        The seed is changed randomly in any number of rounds (defined by rounds).

        :param seed: The seed is a list of starting values.
                     The entries must correspond to the valid function parameters of the function to be tested.
                     For example, if the function under test expects an int, float and a string, a possible seed would be [256, 128.5, "demo"].
                     Only int, float or strings are permitted.
        :type seed: list with any number of int double or strings
        :param rounds: Specifies how many param_set's are to be supplied for the runner. The default is 1.
        :type rounds: int

        :return: Returns a list of lists. Each list in the list is a test case for the ParamRunner.
        :rtype: list
        """
        ### Check types of the input seed ###############################################
        for type in seed:
            if isinstance(type, int):
                self.__logger.debug(str(type) + " is instance of int.")
            elif isinstance(type, float):
                self.__logger.debug(str(type) + " is instance of float.")
            elif isinstance(type, str):
                self.__logger.debug(str(type) + " is instance of str.")
            else:
                self.__logger.error(
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
        self.__logger.debug("Creat new param_set: " + str(seed) + " in round: 0")

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
                            self.__logger.warning(
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
                            self.__logger.warning(
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
                    self.__logger.error(
                        str(value)
                        + " is not a instance of int, float or str."
                        + " Keep value, value is not longer fuzzed."
                    )
                    next_param_set.append(value)

            self.__logger.debug(
                "Creat new param_set: "
                + str(next_param_set)
                + " in round: "
                + str(current_round)
            )
            result_list.append(next_param_set)
            current_round += 1

        self.__logger.debug("Generated param_set: " + str(result_list))
        return result_list

    def fuzz_failed(
        self,
        seed: dict,
        rounds: int = 1,
    ) -> list[list]:
        """The function returns a param_set for a ParamRunner.
        The seed is changed randomly in any number of rounds (defined by rounds).
        In contrast to the fuzz() function, the result dict of the run() function
        of the ParamRunner is passed as a seed.
        The param_set that failed in the test case is fuzzed again according to the number defined in the parameter rounds.

        :param seed: The seed is the result of the fuzz() function of the ParamRunner.
        :type seed: dict
        :param rounds: Specifies how many param_set's are to be supplied for the runner. The default is 1.
        :type rounds: int

        :return: Returns a list of lists. Each list in the list is a test case for the ParamRunner.
        :rtype: list
        """
        # Get failed parameter of the result dict.
        failed_params: dict = seed.get("failed_params", {})
        result_list: list[list] = []

        # call for every failed set the fuzz function.
        for param_list in failed_params.values():
            param_sets = self.fuzz(param_list, rounds)
            for param_set in param_sets:
                result_list.append(param_set)

        return result_list
