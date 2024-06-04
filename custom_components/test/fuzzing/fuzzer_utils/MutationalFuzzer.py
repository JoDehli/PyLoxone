import logging
import random

from custom_components.test.fuzzing.fuzzer_utils.Fuzzer import Fuzzer


class ValuePoolFuzzer(Fuzzer):
    """Value pool fuzzer class, inherits from the abstract fuzzer class."""

    _logger = None

    def __init__(self):
        """Constructor get the logger."""
        self._logger = logging.getLogger(__name__)

    def __delete_random_char(s: str) -> str:
        """Returns s with a random character deleted.

        This function takes a string `s` as input and returns a new string
        with one random character removed from it.

        :param s: Any string from which a character is to be removed.
        :type s: str

        :return: Returns the input string `s` with one randomly chosen character deleted.
        :rtype: str
        """
        if s == "":
            # If the string is empty, there's no character to delete, so return the empty string.
            return s

        # Generate a random integer position within the range of the string's indices.
        pos = random.randint(0, len(s) - 1)

        # Create a new string by excluding the character at the random position.
        # This is done by concatenating the substring before the random position and
        # the substring after the random position.
        return s[:pos] + s[pos + 1 :]

    def __insert_random_char(s: str) -> str:
        """Returns s with a random character inserted.

        This function takes a string `s` as input and returns a new string
        with a random character inserted at a random position within the string.

        :param s: Any string where a character is to be inserted.
        :type s: str

        :return: Returns the input string `s` with one randomly chosen character inserted at a random position.
        :rtype: str
        """
        # Generate a random position within the range of the string's length (including the end of the string).
        pos = random.randint(0, len(s))

        # Generate a random character from the ASCII range 32 to 126 (printable characters).
        random_character = chr(random.randrange(32, 127))

        # Create a new string by inserting the random character at the random position.
        # This is done by concatenating the substring before the random position, the random character,
        # and the substring after the random position.
        return s[:pos] + random_character + s[pos:]

    def __flip_random_char(s: str) -> str:
        """Returns s with a random bit flipped in a random position.

        This function takes a string `s` as input and returns a new string
        where one randomly chosen character has one of its bits flipped
        at a random bit position.

        :param s: Any string where a character's bit is to be flipped.
        :type s: str

        :return: Returns the input string `s` with one character's bit flipped at a random position.
        :rtype: str
        """
        if s == "":
            # If the string is empty, there's no character to flip, so return the empty string.
            return s

        # Generate a random integer position within the range of the string's indices.
        pos = random.randint(0, len(s) - 1)

        # Get the character at the randomly chosen position.
        c = s[pos]

        # Generate a random bit position between 0 and 6 (since we are assuming 7-bit ASCII characters).
        bit = 1 << random.randint(0, 6)

        # Flip the bit at the generated bit position using XOR.
        new_c = chr(ord(c) ^ bit)

        # Create a new string by replacing the character at the random position with the new character.
        # This is done by concatenating the substring before the random position, the new character,
        # and the substring after the random position.
        return s[:pos] + new_c + s[pos + 1 :]

    def __int_add_random_(self, n: int) -> int:
        return n

    def __int_sub_random_(self, n: int) -> int:
        return n

    def __int_mult_random_(self, n: int) -> int:
        return n

    def __int_div_random_(self, n: int) -> int:
        return n

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
