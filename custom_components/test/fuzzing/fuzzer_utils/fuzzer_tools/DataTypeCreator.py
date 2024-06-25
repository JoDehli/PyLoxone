import random
import string

class DataTypeCreator:

    __MAX_INT = (1 << 31) - 1
    __MAX_UINT = (1 << 32) - 1

    def __init__(self):
        """initialize DataTypeCreator"""

    def create_int(self, amount_digits: int = 10, random_creation: bool = True) -> int:
        """Returns an int value with a certain number of digits.

        This function takes a value 'amount_digits' and returns an integer with this amount of digits.

        :param amount_digits: Amount of digits the integer should have
        :type amount_digits: int

        :param random_creation: 
        :type random_creation: boolean

        :return: Returns an integer with a certain amount of digits.
        :rtype: int
        """
        if random_creation == True:
            random_seed_value = random.randint(-self.__MAX_INT, self.__MAX_INT)
            return random_seed_value
        else:
            seed_value = ''
            for digit in range(amount_digits):
                if digit == 0:
                    # Decide if negative of positive int
                    rand_val = random.randint(0,1)
                    if rand_val == 0:
                        seed_value += '-'
                    # First digit should not be a 0
                    rand_val = str(random.randint(1,9))
                    seed_value += rand_val
                else:
                    rand_val = str(random.randint(0,9))
                    seed_value += rand_val

                    # cast to int type and append to seed
                    if digit == amount_digits-1:
                        return int(seed_value)
            
    def create_uint(self, amount_digits: int = 10, random_creation: bool = True) -> int:
        """Returns an uint value with a certain number of digits.

        This function takes a value 'amount_digits' and returns an unsigned integer with this amount of digits.

        :param amount_digits: Amount of digits the unsigned integer should have
        :type amount_digits: uint

        :return: Returns an unsigned integer with a certain amount of digits.
        :rtype: int
        """
        if random_creation == True:
            random_seed_value = random.randint(0, self.__MAX_UINT)
            return random_seed_value
        else:
            seed_value = ''
            for digit in range(amount_digits):
                if digit == 0:
                    # First digit should not be a 0
                    rand_val = str(random.randint(1,9))
                    seed_value += rand_val
                else:
                    rand_val = str(random.randint(0,9))
                    seed_value += rand_val

                    # cast to int type and append to seed
                    if digit == amount_digits-1:
                        return int(seed_value)

    def create_float(self, amount_digits: int) -> int:
        """Returns an int value with a certain number of digits.

        This function takes a value 'amount_digits' and returns an integer with this amount of digits.

        :param amount_digits: Amount of digits the integer should have
        :type amount_digits: int

        :return: Returns an integer with a certain amount of digits.
        :rtype: int
        """
        print("create float")

    def create_string_only_letters(self, amount_chars: int) -> int:
        """Returns an string with a certain number of chars.

        This function takes a value 'amount_chars' and returns an string with this amount of chars.

        :param amount_chars: Amount of chars the string should have
        :type amount_chars: int

        :return: Returns an string with a certain amount of chars.
        :rtype: string
        """
        seed_value = ''
        for character in range(amount_chars):
            random_letter = random.choice(string.ascii_letters)

            seed_value += random_letter

            # cast to int type and append to seed
            if character == amount_chars-1:
                return seed_value
            
    def create_string_special_characters(self, amount_chars: int) -> str:
        """Returns an string with a certain number of chars.

        This function takes a value 'amount_chars' and returns an string with this amount of chars.
        The string includes uppercase and lowercase letters and special charakters.
        Special charakters = "!@#$%^&*()_+-=[]{}|;:',.<>?/`~".

        :param amount_chars: Amount of chars the string should have
        :type amount_chars: int

        :return: Returns an string with a certain amount of chars.
        :rtype: string
        """
        special_characters = "!@#$%^&*()_+-=[]{}|;:',.<>?/`~"
        seed_value = ''
        for character in range(amount_chars):
            rand_value = random.randint(0,4)
            if rand_value == 0:
                random_letter = random.choice(special_characters)
            else:
                random_letter = random.choice(string.ascii_letters)

            seed_value += random_letter

            # cast to int type and append to seed
            if character == amount_chars-1:
                return seed_value
    
    def create_random_string(self, amount_chars: int) -> int:
        """Returns an string with a certain number of chars.

        This function takes a value 'amount_chars' and returns an string with this amount of chars.

        :param amount_chars: Amount of chars the string should have
        :type amount_chars: int

        :return: Returns an string with a certain amount of chars.
        :rtype: string
        """

    def create_byte(self, amount_digits: int) -> int:
        """Returns an int value with a certain number of digits.

        This function takes a value 'amount_digits' and returns an integer with this amount of digits.

        :param amount_digits: Amount of digits the integer should have
        :type amount_digits: int

        :return: Returns an integer with a certain amount of digits.
        :rtype: int
        """
        print("create byte")

