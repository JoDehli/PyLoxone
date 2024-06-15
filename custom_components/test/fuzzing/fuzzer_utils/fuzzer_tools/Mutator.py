from random import random
import math

class Mutator:
    def __init__(self):
        """initialize Mutator"""
        print("Initialize Mutator")

    def delete_random_char(self, string: str) -> str:
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
    
    def insert_random_char(self, string: str) -> str:
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
    
    def flip_random_char(self, string: str) -> str:
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
    
    def get_random_float(self) -> float:
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
    
    def check_inf(self, number: float) -> float:
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
    
    def add_random_number(self, number: float) -> float:
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
    
    def sub_random_number(self, number: float) -> float:
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
    
    def mult_random_number(self, number: float) -> float:
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
    
    def div_random_number(self, number: float) -> float:
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